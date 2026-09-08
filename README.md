# Manga Bubble Cleaner

Una herramienta para detectar y limpiar globos de texto en imágenes de manhwas/mangas, preparadas para traducción.

## Características

- **Detección de globos de texto**: Usa algoritmos OpenCV para detectar globos de diálogo automáticamente
- **Limpieza inteligente**: Utiliza inpainting para rellenar los globos sin afectar el arte original
- **Interfaz web intuitiva**: Sube imágenes fácilmente a través del navegador
- **Compatible múltiples formatos**: Soporta PNG, JPG, JPEG, GIF, WEBP
- **Sin dependencias externas**: Solo Python estándar + OpenCV + Flask

## Instalación Rápida

### Requisitos previos

- Python 3.8+ 
- uv (gestor de paquetes rápido) - **recomendado**
- O pip si prefieres el estándar de Python

### Instalar dependencias

```bash
# Navegar al directorio del proyecto
cd manga-cleaner

# Usando uv (más rápido)
uv pip install -r requirements.txt

# O usando pip
pip install -r requirements.txt
```

## Uso

### Interfaz Web (recomendado para principiantes)

```bash
python web_app.py
```

Luego abre en tu navegador: **http://localhost:5000**

![Interfaz](templates/index.html)

### Línea de comandos

```bash
# Procesar una sola imagen (mantiene el nombre original con _cleaned)
python app.py path/to/image.png

# Guardar en ubicación específica
python app.py path/to/image.png -o output.png

# Procesar todas las imágenes de una carpeta
python app.py path/to/folder

# Procesar sin detección YOLO (solo OpenCV - más rápido)
python app.py image.png --no-yolo

# Procesar carpeta con formato específico
python app.py path/to/folder -e .jpg
```

### Opciones de la línea de comandos

```
usage: app.py [-h] [-o OUTPUT] [-m MODEL] [--no-yolo] [-e EXTENSION] input_path

positional arguments:
  input_path            Ruta a la imagen o carpeta de imágenes

optional arguments:
  -h, --help            show this help message and exit
  -o OUTPUT, --output OUTPUT
                        Ruta de salida (opcional)
  -m MODEL, --model MODEL
                        Ruta al modelo YOLO para detección de globos (mejor precisión)
  --no-yolo             No usar detección YOLO (usar solo OpenCV - más rápido)
  -e EXTENSION, --extension EXTENSION
                        Extensión de archivos a procesar (por defecto: .png)
```

## Ejemplo rápido

```bash
# 1. Procesar una imagen de ejemplo
python demo.py

# 2. Ver las imágenes generadas en el directorio
#    - demo_original.png (imagen original con globos)
#    - demo_detection.png (detección de globos en verde)
#    - demo_cleaned.png (imagen limpiada)

# 3. O abrir directamente la interfaz web
python web_app.py
```

## Cómo funciona

1. **Detección de globos**: Nuestro algoritmo analiza la imagen para encontrar áreas que típicamente contienen globos de texto (bordes blancos con fondo de colores)
2. **Inpainting inteligente**: Para cada globo detectado, se rellena el área usando técnicas de inpainting avanzadas que preservan el estilo del fondo
3. **Salida**: La imagen procesada tiene los globos de texto limpios y listos para ser leídos o traducidos

## Archivos del proyecto

```
manga-cleaner/
├── app.py              # Núcleo de la aplicación (CLI y procesamiento)
├── web_app.py          # Interfaz web con Flask
├── demo.py             # Script de demostración
├── requirements.txt    # Dependencias
├── README.md           # Este archivo
└── templates/
    ├── index.html      # Página principal de la web
    └── result.html     # Página de resultados
```

## Requisitos

```txt
opencv-python>=4.8.0
numpy>=1.24.0
flask>=2.0.0
werkzeug>=2.0.0
```

## Limitaciones actuales

- Los globos deben tener forma visible (rectangular u elíptica)
- No procesa manhwas muy densos (muchos globos por página) de forma óptima
- La calidad del inpainting depende del fondo (dibujos con líneas finas pueden no limpiarse perfectamente)

## Mejoras futuras

- Detección de globos de ojos (eye bubbles)
- Detección directa de texto sin necesidad de globos
- Traducción automática integrada (Google Translate, DeepL, etc.)
- Soporte para PDFs multi-página
- Modo batch con barrera de progreso

## Licencia

MIT License - Libre para uso personal y comercial

## Créditos

Desarrollado con Python, OpenCV y Flask.