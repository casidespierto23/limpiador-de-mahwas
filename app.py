#!/usr/bin/env python3
"""
Manga Bubble Cleaner - App para limpiar globos de texto de manhwas
"""

import cv2
import numpy as np
from pathlib import Path
import argparse
from typing import List, Tuple, Optional

try:
    from ultralytics import YOLO
    YOLO_AVAILABLE = True
except ImportError:
    YOLO_AVAILABLE = False

try:
    import easyocr
    EASYOCR_AVAILABLE = True
except ImportError:
    EASYOCR_AVAILABLE = False


class MangaBubbleCleaner:
    """Limpia globos de texto de páginas de manga/manhwa"""
    
    def __init__(self, model_path: Optional[str] = None):
        """
        Inicializa el limpiador
        
        Args:
            model_path: Ruta al modelo YOLO para detección de globos
        """
        self.model = None
        if model_path and YOLO_AVAILABLE:
            self.model = YOLO(model_path)
        
    def detect_bubbles_opencv(
        self,
        image: np.ndarray,
        white_threshold: int = 200,
        min_contour_area: int = 1500,
        max_contour_area: int = None,
        require_convex: bool = False,
        tightness: float = 0.25
    ) -> List[Tuple[int, int, int, int]]:
        """
        Detección de globos usando OpenCV.

        Estrategia que funciona tanto con fondos oscuros como con fondos
        blancos (webtoons):
          1. Aisla el relleno claro del globo (blanco y cian de pensamiento).
          2. Descarta todo lo que toca el borde de la página (fondo).
          3. Solo acepta regiones con un ANILLO OSCURO alrededor (el contorno
             negro del globo) y poca tinta en el interior (el texto es escaso
             en comparación con el dibujo de un panel).

        Args:
            image: Imagen BGR
            white_threshold: Umbral del canal V (brillo) para el relleno
            min_contour_area: Área mínima del contorno (px)
            max_contour_area: Área máxima del contorno (px). Por defecto el 70%
                              del área de la imagen (para no tomar el fondo).
            require_convex: Si True, exige contornos estrictamente convexos
            tightness: Compacidad mínima (área del contorno / área del hull).
        """
        bubbles = [box for box, _ in self.detect_bubbles_with_masks(
            image,
            white_threshold=white_threshold,
            min_contour_area=min_contour_area,
            max_contour_area=max_contour_area,
            require_convex=require_convex,
            tightness=tightness,
        )]
        return bubbles

    def detect_bubbles_with_masks(
        self,
        image: np.ndarray,
        white_threshold: int = 200,
        min_contour_area: int = 1500,
        max_contour_area: int = None,
        require_convex: bool = False,
        tightness: float = 0.25,
        ring_dark_min: float = 0.18,
        interior_dark_max: float = 0.30,
    ) -> List[Tuple[Tuple[int, int, int, int], np.ndarray]]:
        """
        Igual que detect_bubbles_opencv pero devuelve pares
        (bounding_box, máscara_del_globo) para poder limpiar
        únicamente dentro del polígono real del globo.
        """
        img_h, img_w = image.shape[:2]
        img_area = img_h * img_w
        effective_max = int(0.7 * img_area)
        if max_contour_area is not None:
            effective_max = min(effective_max, max_contour_area)

        # Convertir a HSV
        hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
        h, s, v = cv2.split(hsv)

        # Relleno claro: blanco / casi blanco
        _, white_mask = cv2.threshold(v, white_threshold, 255, cv2.THRESH_BINARY)
        _, sat_mask = cv2.threshold(s, 80, 255, cv2.THRESH_BINARY_INV)

        # Globos de pensamiento (tonalidad cian/azul, típico en manhwas).
        # Atención: en OpenCV el canal H va de 0 a 179 (no 0-255).
        h_idx = h.astype(np.int16)
        cyan_mask = (
            (h_idx >= 80) & (h_idx <= 96) &
            (s >= 30) & (v >= 150)
        ).astype(np.uint8) * 255

        mask = cv2.bitwise_or(cv2.bitwise_and(white_mask, sat_mask), cyan_mask)

        # Limpieza ligera (sin cerrar agujeros a lo grande: no fundir fondos)
        k_small = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, k_small, iterations=1)

        # ---- Descartar el fondo: todo lo claro que toca el borde de la página
        n_labels, labels, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
        border_labels = set()
        for lab in range(1, n_labels):
            lx, ly, lw, lh = stats[lab][0], stats[lab][1], stats[lab][2], stats[lab][3]
            if lx <= 0 or ly <= 0 or lx + lw >= img_w or ly + lh >= img_h:
                border_labels.add(lab)
        if border_labels:
            for lab in border_labels:
                mask[labels == lab] = 0
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, k_small, iterations=1)

        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        dark = (gray < 120)
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        candidates = []
        for contour in contours:
            area = cv2.contourArea(contour)
            if area < min_contour_area or area > effective_max:
                continue

            if require_convex and not cv2.isContourConvex(contour):
                continue
            if not require_convex:
                hull = cv2.convexHull(contour)
                hull_area = cv2.contourArea(hull)
                if hull_area > 0 and area / hull_area < tightness:
                    continue

            comp = np.zeros_like(gray)
            cv2.drawContours(comp, [contour], -1, 255, -1)

            # ---- Anillo oscuro alrededor (borde negro del globo)
            ring = cv2.dilate(comp, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (11, 11)))
            ring = cv2.subtract(ring, comp)
            ring_total = (ring > 0).sum()
            if ring_total == 0:
                continue
            ring_dark = (dark & (ring > 0)).sum() / ring_total

            # ---- Tinta dentro del globo (texto): escasa en un globo real
            interior = cv2.erode(comp, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (13, 13)))
            interior_total = (interior > 0).sum()
            interior_dark = (dark & (interior > 0)).sum() / max(1, interior_total)

            # Uniformidad del relleno: un globo es un área clara y lisa.
            # El dibujo de un panel tiene sombreado/tramas (varianza alta).
            interior_gray = gray[interior > 0]
            smooth = True
            if len(interior_gray) > 30:
                no_text = interior_gray[interior_gray > 140]
                if len(no_text) > 20:
                    smooth = float(no_text.std()) < 40.0
                else:
                    smooth = False

            # Un globo tiene contorno negro; un panel/arte no suele tenerlo.
            if ring_dark < ring_dark_min:
                continue
            # Un globo tiene poca tinta dentro (solo texto). Los paneles con
            # dibujo denso se descartan.
            if interior_dark > interior_dark_max:
                continue
            # Sin texto: aceptar solo si el contorno es fuerte o el relleno liso.
            if interior_dark < 0.01 and ring_dark < 0.40 and not smooth:
                continue

            x, y, w, h = cv2.boundingRect(contour)
            if w < 12 or h < 12:
                continue
            aspect = max(w, h) / max(1, min(w, h))
            if aspect > 8.0:
                continue

            candidates.append(((x, y, x + w, y + h), comp))

        # ---- Eliminar cajas muy superpuestas (quedarse con la mayor)
        kept = []
        for box, comp in sorted(candidates, key=lambda bc: -((bc[0][2] - bc[0][0]) * (bc[0][3] - bc[0][1]))):
            overlap = False
            for (kx1, ky1, kx2, ky2), _ in kept:
                ix1 = max(box[0], kx1)
                iy1 = max(box[1], ky1)
                ix2 = min(box[2], kx2)
                iy2 = min(box[3], ky2)
                if ix2 > ix1 and iy2 > iy1:
                    inter = (ix2 - ix1) * (iy2 - iy1)
                    if inter > 0.5 * ((box[2] - box[0]) * (box[3] - box[1])):
                        overlap = True
                        break
            if not overlap:
                kept.append((box, comp))

        return kept
    
    def detect_bubbles_yolo(self, image: np.ndarray) -> List[Tuple[int, int, int, int]]:
        """
        Detección de globos usando modelo YOLOv8
        """
        if not self.model:
            return self.detect_bubbles_opencv(image)
        
        results = self.model(image, verbose=False)
        bubbles = []
        
        for result in results:
            for box in result.boxes:
                x1, y1, x2, y2 = map(int, box.xyxy[0].tolist())
                bubbles.append((x1, y1, x2, y2))
        
        return bubbles
    
    def _non_max_suppression(self, boxes: np.ndarray, score_threshold: float = 0.3) -> List[Tuple[int, int, int, int]]:
        """Elimina bounding boxes superpuestos"""
        if len(boxes) == 0:
            return []
        
        keep = []
        for i, box in enumerate(boxes):
            x1, y1, x2, y2 = box
            overlap = False
            
            for kept in keep:
                kx1, ky1, kx2, ky2 = kept
                # Calcular intersección
                ix1 = max(x1, kx1)
                iy1 = max(y1, ky1)
                ix2 = min(x2, kx2)
                iy2 = min(y2, ky2)
                
                if ix2 > ix1 and iy2 > iy1:
                    # Hay superposición
                    intersection = (ix2 - ix1) * (iy2 - iy1)
                    area1 = (x2 - x1) * (y2 - y1)
                    if intersection / area1 > score_threshold:
                        overlap = True
                        break
            
            if not overlap:
                keep.append((int(x1), int(y1), int(x2), int(y2)))
        
        return keep
    
    def inpaint_bubble(
        self,
        image: np.ndarray,
        x1: int,
        y1: int,
        x2: int,
        y2: int,
        radius: int = 3,
        bubble_mask: Optional[np.ndarray] = None
    ) -> np.ndarray:
        """
        Rellena el texto dentro de un área de globo usando inpainting

        Args:
            image: Imagen BGR
            x1, y1, x2, y2: Coordenadas del bounding box del globo
            radius: Radio del algoritmo de inpainting (mayor = más agresivo)
            bubble_mask: Máscara (0/255, tamaño de la imagen) con el polígono
                         real del globo. Si se proporciona, solo se limpia
                         dentro de ella (no se toca el dibujo exterior).
        """
        # Recortar región
        roi = image[y1:y2, x1:x2].copy()
        h, w = roi.shape[:2]
        
        # Crear máscara para texto: el globo es blanco, el texto es oscuro.
        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        
        # Zona permitida: interior del polígono del globo
        if bubble_mask is not None:
            roi_mask = bubble_mask[y1:y2, x1:x2].copy()
            # Excluir el borde negro del globo (anillo de ~4px)
            roi_mask = cv2.erode(roi_mask, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9)))
        else:
            roi_mask = np.zeros_like(gray)
            margin_x = max(2, w // 25)
            margin_y = max(2, h // 25)
            roi_mask[margin_y:h - margin_y, margin_x:w - margin_x] = 255
        
        # Texto = píxeles oscuros dentro de la zona permitida
        thresh = np.where((gray < 170) & (roi_mask > 0), 255, 0).astype(np.uint8)
        
        # Cerrar huecos entre trazos y engrosar para cubrir el antialiasing
        kernel = np.ones((3, 3), np.uint8)
        thresh = cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, kernel, iterations=1)
        thresh = cv2.dilate(thresh, kernel, iterations=1)
        
        # Si no hay texto, devolver sin tocar
        if not thresh.any():
            return image
        
        # Inpaint usando Telea (método de examiner)
        inpainted = cv2.inpaint(roi, thresh, radius, cv2.INPAINT_TELEA)
        
        # Reemplazar en la imagen original
        result = image.copy()
        result[y1:y2, x1:x2] = inpainted
        
        return result
    
    def find_text_rows(
        self,
        image: np.ndarray,
        dark_threshold: int = 150,
        min_glyphs: int = 4
    ) -> List[List[Tuple[int, int, int, int]]]:
        """
        Busca filas de texto (conjuntos de glifos alineados horizontalmente).

        Cada fila devuelta es una lista de cajas de glifos (x, y, w, h).
        Se usa para limpiar texto que está directamente sobre el fondo
        (burbujas sin contorno), con filtros que evitan confundirlo con
        líneas del dibujo.
        """
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        h_page, w_page = gray.shape
        dark = (gray < dark_threshold).astype(np.uint8) * 255
        n_labels, labels, stats, _ = cv2.connectedComponentsWithStats(dark, 8)

        comps = []
        for lab in range(1, n_labels):
            x, y, w, h, a = stats[lab]
            if not (8 <= a <= 900):
                continue
            if not (5 <= h <= min(60, int(0.05 * h_page))):
                continue
            aspect = w / max(1, h)
            if not (0.2 <= aspect <= 3.0):
                continue
            comps.append((x, y, w, h, a, lab))

        # Agrupar glifos que se solapan verticalmente -> filas
        rows = []
        for comp in comps:
            x, y, w, h, a, lab = comp
            for r in rows:
                if y <= r[1] and y + h >= r[0]:
                    r[0] = min(r[0], y)
                    r[1] = max(r[1], y + h)
                    r[2].append(comp)
                    break
            else:
                rows.append([y, y + h, [comp]])

        result = []
        for r in rows:
            glyphs = r[2]
            if len(glyphs) < min_glyphs:
                continue
            heights = [c[3] for c in glyphs]
            med = float(np.median(heights))
            if med <= 0 or max(heights) / med > 2.5:
                continue
            # Cajas (x, y, w, h) para el inpainting
            result.append([(c[0], c[1], c[2], c[3]) for c in glyphs])
        return result

    def inpaint_free_text(
        self,
        image: np.ndarray,
        rows: List[List[Tuple[int, int, int, int]]],
        radius: int = 3,
        light_ring: int = 165,
        min_light: float = 0.55
    ) -> np.ndarray:
        """
        Elimina el texto libre (sin globo) haciendo inpainting únicamente
        sobre los píxeles oscuros de cada glifo, y solo si el anillo que lo
        rodea es mayoritariamente claro (así no se toca el dibujo entintado).
        """
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        h_page, w_page = gray.shape
        mask = np.zeros_like(gray)

        for glyphs in rows:
            for (x, y, w, h) in glyphs:
                bx0, bx1 = max(0, x - 3), min(w_page - 1, x + w + 3)
                by0, by1 = max(0, y - 3), min(h_page - 1, y + h + 3)
                pad = gray[by0:by1 + 1, bx0:bx1 + 1]

                gx, gy = x - bx0, y - by0
                glyph_zone = np.zeros((by1 - by0 + 1, bx1 - bx0 + 1), bool)
                glyph_zone[gy:gy + h, gx:gx + w] = gray[y:y + h, x:x + w] < 150

                ring_zone = np.ones_like(glyph_zone)
                ring_zone[gy:gy + h, gx:gx + w] = False
                if not ring_zone.any():
                    continue
                ring = pad[ring_zone]
                if ring.size == 0 or float((ring > light_ring).mean()) < min_light:
                    continue

                mask[by0:by1 + 1, bx0:bx1 + 1] |= (glyph_zone.astype(np.uint8) * 255)

        if not mask.any():
            return image

        mask = cv2.dilate(mask, np.ones((3, 3), np.uint8), iterations=1)
        return cv2.inpaint(image, mask, radius, cv2.INPAINT_TELEA)

    def process_image(
        self, 
        image_path: str, 
        output_path: Optional[str] = None,
        use_yolo: bool = True
    ) -> np.ndarray:
        """
        Procesa una imagen para limpiar todos los globos
        
        Args:
            image_path: Ruta a la imagen del manga
            output_path: Ruta para guardar la imagen procesada
            use_yolo: Si usar detección YOLO (requiere modelo)
            
        Returns:
            Imagen procesada
        """
        # Leer imagen
        image = cv2.imread(image_path)
        if image is None:
            raise ValueError(f"No se pudo leer la imagen: {image_path}")
        
        print(f"Procesando: {image_path}")
        print(f"Tamaño: {image.shape[1]}x{image.shape[0]} píxeles")
        
        # Detectar globos
        print("Detectando globos de texto...")
        if use_yolo and self.model:
            bubbles = self.detect_bubbles_yolo(image)
        else:
            bubbles = self.detect_bubbles_opencv(image)
        
        print(f"Encontrados {len(bubbles)} globos")
        
        # Limpiar cada globo
        result = image.copy()
        for i, (x1, y1, x2, y2) in enumerate(bubbles):
            print(f"  Limpiando globo {i+1}/{len(bubbles)} en ({x1}, {y1}, {x2}, {y2})")
            result = self.inpaint_bubble(result, x1, y1, x2, y2)
        
        # Guardar resultado
        if output_path is None:
            output_path = image_path.replace('.', '_cleaned.')
        
        cv2.imwrite(output_path, result)
        print(f"Imagen guardada en: {output_path}")
        
        return result
    
    def process_folder(
        self, 
        folder_path: str, 
        output_folder: Optional[str] = None,
        extension: str = '.png'
    ) -> List[str]:
        """
        Procesa todas las imágenes de una carpeta
        
        Args:
            folder_path: Ruta a la carpeta con imágenes
            output_folder: Carpeta de salida (si no, se guarda al lado)
            extension: Extensión de archivos a procesar
            
        Returns:
            Lista de rutas de imágenes procesadas
        """
        folder = Path(folder_path)
        images = list(folder.glob(f'*{extension}')) + \
                 list(folder.glob(f'*{extension.upper()}'))
        
        if not images:
            print(f"No se encontraron imágenes con extensión {extension}")
            return []
        
        print(f"Encontradas {len(images)} imágenes para procesar")
        
        processed = []
        for img_path in images:
            output_path = output_folder / f"{img_path.stem}_cleaned{img_path.suffix}" if output_folder else None
            try:
                self.process_image(str(img_path), str(output_path) if output_path else None)
                processed.append(str(output_path) if output_path else str(img_path.replace('.', '_cleaned.')))
            except Exception as e:
                print(f"Error procesando {img_path}: {e}")
        
        return processed


def main():
    parser = argparse.ArgumentParser(
        description='Limpia globos de texto de manhwas/mangas'
    )
    parser.add_argument(
        'input_path',
        help='Ruta a la imagen o carpeta de imágenes'
    )
    parser.add_argument(
        '-o', '--output',
        help='Ruta de salida (opcional)',
        default=None
    )
    parser.add_argument(
        '-m', '--model',
        help='Ruta al modelo YOLO para detección de globos',
        default=None
    )
    parser.add_argument(
        '--no-yolo',
        action='store_true',
        help='No usar detección YOLO (usar solo OpenCV)'
    )
    parser.add_argument(
        '-e', '--extension',
        default='.png',
        help='Extensión de archivos a procesar (por defecto: .png)'
    )
    
    args = parser.parse_args()
    
    # Verificar dependencias
    if args.model and not YOLO_AVAILABLE:
        print("ERROR: ultralytics no está instalado. Instala con: pip install ultralytics")
        return
    
    # Crear limpiador
    cleaner = MangaBubbleCleaner(model_path=args.model)
    
    # Procesar
    input_path = Path(args.input_path)
    if input_path.is_file():
        cleaner.process_image(
            str(input_path),
            args.output,
            use_yolo=not args.no_yolo
        )
    elif input_path.is_dir():
        output_folder = Path(args.output) if args.output else None
        cleaner.process_folder(
            str(input_path),
            output_folder,
            args.extension
        )
    else:
        print(f"ERROR: {args.input_path} no es un archivo o carpeta válido")


if __name__ == '__main__':
    main()