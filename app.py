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
        
    def detect_bubbles_opencv(self, image: np.ndarray) -> List[Tuple[int, int, int, int]]:
        """
        Detección de globos usando OpenCV
        Método basado en HSV y detección de bordes
        """
        # Convertir a HSV
        hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
        h, s, v = cv2.split(hsv)
        
        # Máscara de valores altos (colores claros/blancos)
        _, white_mask = cv2.threshold(v, 160, 255, cv2.THRESH_BINARY)
        
        # Máscara de saturación baja (colores planos como globos)
        _, sat_mask = cv2.threshold(s, 60, 255, cv2.THRESH_BINARY_INV)
        
        # Combinar máscaras
        mask = cv2.bitwise_and(white_mask, sat_mask)
        
        # Morphology para limpiar
        kernel = np.ones((3,3), np.uint8)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=1)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel, iterations=1)
        
        # Contornos
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        bubbles = []
        
        for contour in contours:
            area = cv2.contourArea(contour)
            
            # Tamaño típico de globos
            if area < 500 or area > 80000:
                continue
            
            # Convexidad
            if not cv2.isContourConvex(contour):
                continue
            
            x, y, w, h = cv2.boundingRect(contour)
            aspect = w / h if h > 0 else 0
            
            # Aspect ratio razonable para elípticos/rectangulares
            if not (0.3 < aspect < 4.0):
                continue
            
            # Verificar que sea claramente más claro que el fondo
            roi_gray = gray[y:y+h, x:x+w]
            avg_brightness = np.mean(roi_gray)
            
            # Brillo del fondo (esquina superior izquierda)
            margin = 10
            bg_brightness = np.mean(gray[margin:margin+20, margin:margin+20])
            
            if avg_brightness > bg_brightness + 30:
                bubbles.append((x, y, x+w, y+h))
        
        # Filtrar superposiciones de bounding boxes
        if bubbles:
            filtered = []
            for box in sorted(bubbles, key=lambda b: -((b[2]-b[0])*(b[3]-b[1]))):
                overlap = False
                for kept in filtered:
                    ix1 = max(box[0], kept[0])
                    iy1 = max(box[1], kept[1])
                    ix2 = min(box[2], kept[2])
                    iy2 = min(box[3], kept[3])
                    if ix2 > ix1 and iy2 > iy1:
                        overlap = True
                        break
                if not overlap:
                    filtered.append(box)
            bubbles = filtered
        
        return bubbles
    
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
    
    def inpaint_bubble(self, image: np.ndarray, x1: int, y1: int, x2: int, y2: int) -> np.ndarray:
        """
        Rellena un área de globo usando inpainting
        """
        # Recortar región
        roi = image[y1:y2, x1:x2].copy()
        
        # Crear máscara para texto (usando threshold)
        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        
        # Threshold adaptativo para detectar texto
        thresh = cv2.adaptiveThreshold(
            gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, 
            cv2.THRESH_BINARY_INV, 11, 2
        )
        
        # Morphological operations para limpiar
        kernel = np.ones((2,2), np.uint8)
        thresh = cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, kernel, iterations=1)
        
        # Inpaint usando Telea (método de exemplar)
        inpainted = cv2.inpaint(roi, thresh, 3, cv2.INPAINT_TELEA)
        
        # Reemplazar en la imagen original
        result = image.copy()
        result[y1:y2, x1:x2] = inpainted
        
        return result
    
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