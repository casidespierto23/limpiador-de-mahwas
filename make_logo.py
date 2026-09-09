#!/usr/bin/env python3
"""
Genera el logo de Manga Bubble Cleaner (PNG con transparencia + ICO para Windows).

Uso: python make_logo.py [salida.png]
"""
import sys
from pathlib import Path

from PIL import Image, ImageDraw

SIZE = 512
INK = (28, 28, 28, 255)
WHITE = (255, 255, 255, 255)
CYAN = (35, 190, 220, 255)
RED = (242, 82, 96, 255)


def star(draw, cx, cy, r, color):
    pts = [
        (cx, cy - r),
        (cx + r * 0.28, cy - r * 0.28),
        (cx + r, cy),
        (cx + r * 0.28, cy + r * 0.28),
        (cx, cy + r),
        (cx - r * 0.28, cy + r * 0.28),
        (cx - r, cy),
        (cx - r * 0.28, cy - r * 0.28),
    ]
    draw.polygon(pts, fill=color)


def main():
    base = Image.new('RGBA', (SIZE, SIZE), (0, 0, 0, 0))
    d = ImageDraw.Draw(base)

    # Cola del globo (se dibuja antes para que la base la tape en la unión)
    tail = [(150, 396), (330, 396), (244, 492)]
    d.polygon(tail, fill=WHITE)

    # Cuerpo del globo (blanco + borde negro grueso)
    d.rounded_rectangle([72, 64, 440, 404], radius=70, fill=WHITE,
                        outline=INK, width=10)

    # Contorno de la cola (dos laterales + punta)
    d.line([(150, 396), (244, 492)], fill=INK, width=10, joint='curve')
    d.line([(330, 396), (244, 492)], fill=INK, width=10, joint='curve')
    d.polygon([(236, 484), (252, 484), (244, 500)], fill=INK)

    # Líneas de texto dentro del globo (a medio borrar)
    for x1, y, x2 in ((150, 182, 300), (132, 236, 268), (150, 290, 280)):
        d.line([(x1, y), (x2, y)], fill=INK, width=13)

    # Goma de borrar inclinada (roja) con faja blanca
    eraser = Image.new('RGBA', (190, 130), (0, 0, 0, 0))
    ed = ImageDraw.Draw(eraser)
    ed.rounded_rectangle([16, 18, 128, 104], radius=16, fill=RED,
                         outline=INK, width=8)
    ed.rounded_rectangle([128, 18, 172, 104], radius=12, fill=WHITE,
                         outline=INK, width=8)
    eraser = eraser.rotate(28, expand=True, resample=Image.Resampling.BICUBIC)
    base.alpha_composite(eraser, dest=(176, 148))

    # Destellos estilo manhwa alrededor
    for cx, cy, r in ((118, 116, 34), (398, 100, 24), (404, 252, 20)):
        star(d, cx, cy, r, CYAN)

    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path('assets') / 'logo.png'
    out.parent.mkdir(parents=True, exist_ok=True)
    base.save(out)
    print(f'Logo PNG guardado: {out}')

    ico = out.with_suffix('.ico')
    base.save(ico, format='ICO', sizes=[(16, 16), (24, 24), (32, 32),
                                        (48, 48), (64, 64), (128, 128),
                                        (256, 256)])
    print(f'Icono ICO guardado: {ico}')


if __name__ == '__main__':
    main()