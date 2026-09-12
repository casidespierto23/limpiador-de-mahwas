#!/usr/bin/env python3
"""
Extracción de texto (OCR) dentro de los globos de diálogo — versión profesional.

Características:
  * Lee texto de TODOS los globos, incluso los que la detección estricta de
    limpieza dejó pasar: sobre la lista recibida añade una detección laxa
    extra y unifica los conjuntos sin duplicar.
  * Por cada globo intenta varios preprocesados (recorte natural blanqueado,
    versión binarizada y versión invertida para globos oscuros) y se queda
    con el intento de mayor puntuación (más caracteres y mayor confianza).
  * Ordena los globos en orden de lectura (de arriba a abajo, izquierda a
    derecha) como lo leería una persona.
  * Devuelve detalle por globo: texto completo, líneas con su cuadro y
    confianza, y la confianza media del globo.

Usa RapidOCR (onnxruntime) que funciona 100% offline una vez instalados sus
modelos. Por defecto reconoce chino+inglés. Para otros idiomas (coreano,
japonés, etc.) se puede colocar un modelo de reconocimiento en la carpeta
`models/` junto a la app y seleccionarlo con el parámetro `lang`.
"""
import sys
from pathlib import Path

import cv2
import numpy as np

try:
    from rapidocr_onnxruntime import RapidOCR
    RAPIDOCR_AVAILABLE = True
except Exception:  # pragma: no cover - OCR opcional
    RAPIDOCR_AVAILABLE = False


def _base_dir():
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent


def _bubble_overlap(a, b):
    """Intersección dividida por el área del menor: 1 = el menor está dentro."""
    ix1, iy1 = max(a[0], b[0]), max(a[1], b[1])
    ix2, iy2 = min(a[2], b[2]), min(a[3], b[3])
    if ix2 <= ix1 or iy2 <= iy1:
        return 0.0
    inter = (ix2 - ix1) * (iy2 - iy1)
    area = min((a[2] - a[0]) * (a[3] - a[1]),
               (b[2] - b[0]) * (b[3] - b[1]))
    return inter / max(1, area)


class BubbleTextExtractor:
    """Extrae el texto de cada globo (recortando por su máscara) antes de limpiarlo."""

    # lang -> nombre de archivo de modelo de reconocimiento en models/
    REC_MODELS = {
        'ko': 'ko_rec.onnx',
        'ja': 'ja_rec.onnx',
        'zh': 'zh_rec.onnx',
        'en': 'en_rec.onnx',
    }

    def __init__(self):
        self._engine = None
        self._lang = None
        self._load_error = None
        self._cleaner = None

    def is_available(self):
        return RAPIDOCR_AVAILABLE

    @property
    def load_error(self):
        return self._load_error

    def _get_engine(self, lang):
        """Inicializa (una sola vez) el motor RapidOCR para el idioma pedido."""
        if self._engine is not None and self._lang == lang:
            return self._engine
        if not RAPIDOCR_AVAILABLE:
            self._load_error = ('Falta el paquete rapidocr-onnxruntime. '
                                'Instalalo con: uv pip install rapidocr-onnxruntime')
            return None
        try:
            kwargs = {}
            rec_model = self._rec_model_path(lang)
            if rec_model:
                kwargs['rec_model_path'] = str(rec_model)
            self._engine = RapidOCR(**kwargs)
            self._lang = lang
            self._load_error = None
            return self._engine
        except Exception as exc:  # pragma: no cover - depende de descargas
            self._engine = None
            self._load_error = f'No se pudo cargar el OCR: {exc}'
            return None

    def _rec_model_path(self, lang):
        if lang in self.REC_MODELS:
            path = _base_dir() / 'models' / self.REC_MODELS[lang]
            if path.exists():
                return path
        return None

    # ------------------------------------------------------------- preprocesado
    @staticmethod
    def _whiten(roi, mask):
        """Fondo blanco fuera de la máscara, contenido real dentro."""
        out = roi.copy()
        if mask is not None and mask.shape[:2] == roi.shape[:2]:
            out[mask == 0] = 255
        return out

    @staticmethod
    def _binarize(roi, mask):
        """Binarización Otsu del interior: texto oscuro -> negro, fondo -> blanco."""
        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        region = gray.copy()
        if mask is not None and mask.shape[:2] == roi.shape[:2]:
            region[mask == 0] = 255
        _, binimg = cv2.threshold(region, 0, 255,
                                  cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        binimg = cv2.morphologyEx(binimg, cv2.MORPH_CLOSE,
                                  np.ones((3, 3), np.uint8), iterations=1)
        return binimg

    @staticmethod
    def _upscale(img, base_size):
        """Si el globo es chico, se escala para que el texto quede legible."""
        h, w = img.shape[:2]
        if base_size >= 96:
            return img
        scale = min(4.0, 96.0 / max(1, base_size))
        if scale <= 1.0:
            return img
        return cv2.resize(img, (int(w * scale), int(h * scale)),
                          interpolation=cv2.INTER_CUBIC)

    def _crop_variants(self, image, bbox, mask):
        """Varios preparados del mismo globo para intentar hasta leerlo."""
        x1, y1, x2, y2 = bbox
        h, w = y2 - y1 + 1, x2 - x1 + 1
        roi = image[y1:y2 + 1, x1:x2 + 1]
        roi_mask = mask[y1:y2 + 1, x1:x2 + 1] if mask is not None else None
        base = min(h, w)

        variants = []
        wh = self._whiten(roi, roi_mask)
        variants.append(('natural', self._upscale(wh, base)))
        gray = cv2.cvtColor(wh, cv2.COLOR_BGR2GRAY)
        if roi_mask is not None and (roi_mask > 0).any():
            bg = float(gray[roi_mask > 0].mean())
            # Globo oscuro con texto claro: conviene la imagen invertida.
            if bg < 128:
                variants.append(('invertida', self._upscale(
                    cv2.bitwise_not(wh), base)))
        variants.append(('binaria', self._upscale(
            self._binarize(roi, roi_mask), base)))
        return variants

    def _read_bubble(self, image, bbox, mask, engine, min_conf):
        """Intenta cada variante y devuelve las líneas del mejor intento."""
        best, best_score = [], -1.0
        for _name, prep in self._crop_variants(image, bbox, mask):
            try:
                out, _ = engine(prep)
            except Exception:
                continue  # una variante puede fallar; se prueban las demás
            lines = []
            for box, text, conf in (out or []):
                if conf is not None and conf < min_conf:
                    continue
                text = str(text).strip()
                if not text:
                    continue
                pts = [float(c) for pt in box for c in pt]
                xs = pts[0::2]
                ys = pts[1::2]
                lines.append({
                    'box': pts,
                    'bbox': (int(min(xs)), int(min(ys)),
                             int(max(xs)), int(max(ys))),
                    'text': text,
                    'conf': float(conf) if conf is not None else 0.0,
                })
            score = sum(len(l['text']) for l in lines)
            score += 10.0 * sum(l['conf'] for l in lines)
            if score > best_score:
                best, best_score = lines, score
        return best

    # --------------------------------------------------- conjunto completo de globos
    def _all_bubbles(self, image, strict):
        """Globos estrictos (limpieza) + una pasada laxa para no perder ninguno."""
        merged = list(strict)
        if self._cleaner is None:
            try:
                from app import MangaBubbleCleaner
                self._cleaner = MangaBubbleCleaner()
            except Exception:
                return merged
        try:
            loose = self._cleaner.detect_bubbles_with_masks(
                image,
                white_threshold=185,
                min_contour_area=500,
                tightness=0.18,
                ring_dark_min=0.12,
                interior_dark_max=0.45,
            )
        except Exception:
            loose = []
        for box, mask in loose:
            if any(_bubble_overlap(box, kept) > 0.5 for kept, _ in merged):
                continue
            merged.append((box, mask))
        # Orden de lectura: bandas por fila (Y), luego izquierda a derecha (X).
        merged.sort(key=lambda bc: ((bc[0][1] + bc[0][3]) // 200, bc[0][0]))
        return merged

    # ------------------------------------------------------------- extracción
    def extract_bubbles(self, image, detections, lang='auto', min_conf=0.4):
        """
        Extrae el texto de cada globo de la página.

        image      : BGR de la página completa.
        detections : resultado de detect_bubbles_with_masks -> [(box, mask), ...]
        lang       : 'auto', 'ko', 'ja', 'zh' o 'en'.
        min_conf   : confianza mínima para incluir una línea.

        Devuelve una lista de dicts, uno por globo (incluidos los que la
        detección de limpieza no vio), en orden de lectura:
          {'index': n, 'bbox': (x1,y1,x2,y2), 'text': '...', 'lines': [...],
           'conf': 0.0-1.0, 'lang': 'auto'}
        """
        if not self.is_available():
            return None
        engine = self._get_engine(lang)
        if engine is None:
            return None

        results = []
        for n, (bbox, mask) in enumerate(self._all_bubbles(image, detections), 1):
            x1, y1, x2, y2 = bbox
            if x2 - x1 + 1 < 12 or y2 - y1 + 1 < 12:
                continue
            lines = self._read_bubble(image, bbox, mask, engine, min_conf)
            confs = [l['conf'] for l in lines if l['conf'] is not None]
            results.append({
                'index': n,
                'bbox': tuple(bbox),
                'text': '\n'.join(l['text'] for l in lines),
                'lines': lines,
                'conf': float(np.mean(confs)) if confs else 0.0,
                'lang': lang,
            })
        return results

    @staticmethod
    def transcript(results):
        """Texto legible y detallado de todos los globos (mostrar o guardar)."""
        if not results:
            return ''
        blocks = []
        for r in results:
            text = r.get('text', '').strip()
            if not text:
                continue
            head = f'--- Globo {r["index"]}'
            conf = r.get('conf')
            if conf:
                head += f' · conf. {conf:.0%}'
            n_lines = sum(1 for l in r.get('lines', []) if l.get('text', '').strip())
            if n_lines > 1:
                head += f' · {n_lines} líneas'
            blocks.append(head + ' ---\n' + text)
        return '\n\n'.join(blocks)


def transcript(results):
    """Texto legible y detallado de todos los globos (mostrar o guardar)."""
    return BubbleTextExtractor.transcript(results)


def main():
    """Demo: extrae el texto de una imagen (usa detección automática de globos)."""
    if len(sys.argv) < 2:
        print('Uso: python ocr.py <imagen> [idioma]')
        return
    from app import MangaBubbleCleaner
    img = cv2.imread(sys.argv[1])
    if img is None:
        print('No se pudo leer la imagen')
        return
    lang = sys.argv[2] if len(sys.argv) > 2 else 'auto'
    cleaner = MangaBubbleCleaner()
    detections = cleaner.detect_bubbles_with_masks(img)
    print(f'{len(detections)} globos detectados (detección estricta)')
    extractor = BubbleTextExtractor()
    out = extractor.extract_bubbles(img, detections, lang=lang)
    if out is None:
        print(extractor.load_error or 'OCR no disponible')
        return
    con_texto = sum(1 for r in out if r.get('text'))
    media = (sum(r['conf'] for r in out if r.get('conf')) /
             max(1, con_texto))
    print(f'Leídos {con_texto}/{len(out)} globos · conf. media {media:.1%}')
    print(extractor.transcript(out))


if __name__ == '__main__':
    main()