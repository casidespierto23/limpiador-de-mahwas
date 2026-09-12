#!/usr/bin/env python3
"""
Extracción de texto (OCR) dentro de los globos de diálogo.

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

    def is_available(self):
        if not RAPIDOCR_AVAILABLE:
            return False
        return True

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

    @staticmethod
    def _preprocess(roi, mask):
        """Prepara el recorte del globo para OCR: fondo blanco fuera de la
        máscara, relleno real dentro, y escala 2x si el texto es pequeño."""
        roi = roi.copy()
        roi[mask == 0] = 255
        h, w = roi.shape[:2]
        if min(h, w) < 160:
            roi = cv2.resize(roi, (w * 2, h * 2), interpolation=cv2.INTER_CUBIC)
        return roi

    def extract_bubbles(self, image, detections, lang='auto', min_conf=0.4):
        """
        Extrae el texto de cada globo.

        image      : BGR de la página completa.
        detections : resultado de detect_bubbles_with_masks -> [(box, mask), ...]
        lang       : 'auto', 'ko', 'ja', 'zh' o 'en'.
        min_conf   : confianza mínima para incluir una línea.

        Devuelve una lista de dicts:
          {'index': n, 'bbox': (x1,y1,x2,y2), 'text': '...', 'lines': [...]}
        """
        if not self.is_available():
            return None
        engine = self._get_engine(lang)
        if engine is None:
            return None

        results = []
        for n, (bbox, mask) in enumerate(detections, 1):
            x1, y1, x2, y2 = bbox
            w, h = x2 - x1 + 1, y2 - y1 + 1
            if w < 12 or h < 12:
                continue
            roi = image[y1:y2 + 1, x1:x2 + 1]
            roi_mask = mask[y1:y2 + 1, x1:x2 + 1]
            prep = self._preprocess(roi, roi_mask)

            try:
                out, _ = engine(prep)
            except Exception as exc:
                results.append({'index': n, 'bbox': bbox, 'text': f'[error OCR: {exc}]', 'lines': []})
                continue

            lines = []
            if out:
                for box, text, conf in out:
                    if conf is not None and conf < min_conf:
                        continue
                    text = str(text).strip()
                    if not text:
                        continue
                    lines.append({'box': [float(c) for pt in box for c in pt],
                                  'text': text,
                                  'conf': float(conf) if conf is not None else 0.0})
            full = '\n'.join(x['text'] for x in lines)
            results.append({'index': n, 'bbox': bbox, 'text': full, 'lines': lines})

        return results

    @staticmethod
    def transcript(results):
        """Texto legible de todos los globos (para mostrar o guardar)."""
        if not results:
            return ''
        blocks = []
        for r in results:
            if not r.get('text'):
                continue
            blocks.append(f'--- Globo {r["index"]} ---\n{r["text"]}')
        return '\n\n'.join(blocks)


def transcript(results):
    """Texto legible de todos los globos (para mostrar o guardar)."""
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
    print(f'{len(detections)} globos detectados')
    extractor = BubbleTextExtractor()
    out = extractor.extract_bubbles(img, detections, lang=lang)
    if out is None:
        print(extractor.load_error or 'OCR no disponible')
        return
    print(extractor.transcript(out))


if __name__ == '__main__':
    main()