#!/usr/bin/env python3
"""
Demostración del Manga Bubble Cleaner
Crea una imagen de ejemplo y muestra el proceso de limpieza
"""

import cv2
import numpy as np
import os

def create_demo_image():
    """Crea una imagen de manga de ejemplo"""
    # Fondo tipo manga oscuro
    img = np.ones((700, 1200, 3), dtype=np.uint8) * 80
    
    # Renglones de fondo
    for row in range(100, 650, 40):
        cv2.line(img, (50, row), (1150, row), (60, 60, 60), 1)
    
    # Personaje simple
    cv2.circle(img, (400, 350), 50, (220, 180, 140), -1)
    cv2.ellipse(img, (380, 335), (15, 10), 0, 0, 360, (255, 255, 255), -1)
    cv2.circle(img, (380, 335), 6, (0, 0, 0), -1)
    cv2.ellipse(img, (420, 335), (15, 10), 0, 0, 360, (255, 255, 255), -1)
    cv2.circle(img, (420, 335), 6, (0, 0, 0), -1)
    
    # GLOBO 1 - Elíptico izquierdo
    cv2.ellipse(img, (180, 250), (85, 52), 0, 0, 360, (255, 255, 255), -1)
    cv2.ellipse(img, (180, 250), (85, 52), 0, 0, 360, (0, 0, 0), 3)
    
    # GLOBO 2 - Rectangular derecha arriba
    cv2.rectangle(img, (800, 200), (1050, 320), (255, 255, 255), -1)
    cv2.rectangle(img, (800, 200), (1050, 320), (0, 0, 0), 3)
    
    # GLOBO 3 - Elíptico abajo
    cv2.ellipse(img, (350, 580), (70, 45), 0, 0, 360, (255, 255, 255), -1)
    cv2.ellipse(img, (350, 580), (70, 45), 0, 0, 360, (0, 0, 0), 3)
    
    # Texto dentro de los globos (lo que se va a limpiar)
    font = cv2.FONT_HERSHEY_SIMPLEX
    cv2.putText(img, "HOLA MUNDO", (118, 258), font, 0.7, (0, 0, 0), 2, cv2.LINE_AA)
    cv2.putText(img, "QUE TAL?", (830, 240), font, 0.9, (0, 0, 0), 2, cv2.LINE_AA)
    cv2.putText(img, "VAMOS A", (280, 580), font, 0.7, (0, 0, 0), 2, cv2.LINE_AA)
    
    return img


def main():
    print("=" * 60)
    print("  MANGA BUBBLE CLEANER - DEMOSTRACIÓN")
    print("=" * 60)
    
    # Importar limpiador
    from app import MangaBubbleCleaner
    
    cleaner = MangaBubbleCleaner()
    
    # Crear imagen de ejemplo
    print("\n1. Creando imagen de ejemplo...")
    img = create_demo_image()
    
    # Guardar
    demo_path = "demo_image.png"
    cv2.imwrite(demo_path, img)
    print(f"   Imagen guardada: {demo_path}")
    
    # Detectar globos
    print("\n2. Detectando globos de texto...")
    bubbles = cleaner.detect_bubbles_opencv(img)
    print(f"   Encontrados {len(bubbles)} globos")
    
    for i, (x1, y1, x2, y2) in enumerate(bubbles):
        print(f"   - Globo {i+1}: ({x1}, {y1}) - ({x2}, {y2})")
    
    # Limpiar
    print("\n3. Limpiando globos...")
    result = img.copy()
    for i, (x1, y1, x2, y2) in enumerate(bubbles):
        result = cleaner.inpaint_bubble(result, x1, y1, x2, y2)
        print(f"   - Limpiado globo {i+1}")
    
    # Guardar resultado
    result_path = "demo_cleaned.png"
    cv2.imwrite(result_path, result)
    print(f"\n   Imagen limpiada guardada: {result_path}")
    
    print("\n" + "=" * 60)
    print("  DEMOSTRACIÓN COMPLETA")
    print("=" * 60)
    print("\nPara usar la aplicación:")
    print("  1. Escritorio:     python gui_app.py")
    print("  2. Interfaz web:   python web_app.py  (http://localhost:5000)")
    print("  3. Línea de comandos: python app.py path/to/manga_page.png --no-yolo")


if __name__ == '__main__':
    main()