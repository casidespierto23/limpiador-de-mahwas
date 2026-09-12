# Manga Bubble Cleaner

Una herramienta para detectar y limpiar globos de texto en imágenes de manhwas/mangas, preparadas para traducción.

## Características

- **Detección de globos de texto**: Usa algoritmos OpenCV para detectar globos de diálogo automáticamente
- **Limpieza inteligente**: Detecta el globo por su contorno negro y sólo borra el texto dentro de su polígono real (no toca el dibujo exterior), incluso en páginas de fondo blanco
- **Interfaz web intuitiva**: Sube imágenes fácilmente a través del navegador
- **interfaz de escritorio (GUI)**: Aplicación local con panel original/resultado, zoom, detección visual y procesado por lotes
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

### Interfaz de escritorio (GUI)

```bash
python gui_app.py
```

O bien, en Windows: doble clic en `start_gui.bat`.

La GUI ofrece:
- **Original / Procesada** lado a lado con zoom (rueda, + / -, Ajustar, 100%)
- **Comparador antes/después**: en "Vista derecha" elegí **Comparar** y arrastrá el borde vertical para ver qué se borró y qué quedó igual
- **Limpieza automática**: al abrir una página (o con la navegación Anterior/Siguiente) detecta y limpia los globos automáticamente
- **Seguridad anti-daño**: solo se limpia dentro del polígono del globo (por su contorno negro); el fondo blanco de la página no se borra
- **Modo avanzado opcional**: "Borrar también el texto suelto (sin globo)" para texto escrito directamente sobre el fondo (usa filtros de seguridad para no tocar el dibujo)
- **Asistente por pasos** en el panel: 1 · abrí la página, 2 · limpia y extrae texto, 3 · copiá/guardá el texto o la imagen
- **Panel lateral plegable**: usá el botón ◀/▶ del riel izquierdo para ocultar los controles y ganar espacio para las imágenes; el panel de "Texto extraído" también se pliega con ▲
- **Miniaturas de páginas**: una tira debajo del visor muestra todas las páginas del capítulo; hacé clic para saltar
- **Edición manual** para retocar (botones con resaltado + ayuda contextual):
  - **Pincel**: el círculo rojo muestra el tamaño exacto al pasar el ratón; pintá encima del texto y la zona se limpia al soltar (tamaño 5–150 px, con vista previa del trazo)
  - **Rectángulo**: arrastrá para encerrar un globo o palabra; se marca con relleno translúcido y muestra el tamaño en pantalla
  - **Deshacer (n)**: revierte las últimas ediciones paso a paso (hasta 10)
  - **Reiniciar**: descarta las ediciones manuales y vuelve al resultado automático
  - `Esc` cancela la selección/dibujo en curso
- Vista de **detección** (rectángulos verdes numerados) para comprobar los globos encontrados
- Ajustes en vivo: umbral de blancura, área mínima del globo y radio de inpainting (en "Ajustes avanzados")
- **Atajos de teclado**: `Ctrl+O` abrir imagen · `Ctrl+Shift+O` abrir carpeta · `Ctrl+P` procesar página · `Ctrl+S` guardar · `Ctrl+←/→` página anterior/siguiente · `Ctrl++`/`Ctrl+-` zoom · `Ctrl+0` ajustar · `Esc` cancela el dibujo
- **Pantalla de bienvenida** cuando no hay ninguna página para empezar con un solo clic
- **Barra de progreso** durante el procesamiento y navegación de páginas (Anterior / Siguiente) con **procesado por lotes** de una carpeta entera
- **Diseño vivo y agradable** pensado para trabajar con gusto:
  - Cabecera con **degradado** y logo, que se adapta al tamaño de la ventana
  - **Iconos dibujados** en los botones principales (abrir, procesar, guardar, donar)
  - **Avisos tipo toast**: al abrir, procesar, copiar o guardar aparece una notificación flotante que desaparece sola
  - **Destellos de celebración** sobre los globos cuando termina la limpieza
  - **Pistas en la barra de estado** al pasar el ratón por cada botón
- **Ocultar/Mostrar imagen**: el botón "Ocultar imagen" oculta el visor principal
  para trabajar concentrado en los controles y el panel de texto; al volver a
  tocar "Mostrar imagen" reaparece con las mismas vistas

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
├── gui_app.py          # Interfaz de escritorio (tkinter / Pillow)
├── ocr.py              # Extracción de texto con OCR (RapidOCR)
├── web_app.py          # Interfaz web con Flask
├── demo.py             # Script de demostración
├── make_logo.py        # Genera el logo / ícono de la app
├── assets/             # Logo (logo.png) e ícono (logo.ico)
├── requirements.txt    # Dependencias
├── README.md           # Este archivo
├── start.bat           # Inicia la web en Windows
├── start_gui.bat       # Inicia la GUI (usa dist\...exe si está compilado)
├── dist/               # App compilada: "Manga Bubble Cleaner.exe" (con logo)
├── static/
│   └── favicon.png     # Ícono de la interfaz web
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
pillow>=9.0.0
```

## Compilar la app (generar el .exe con logo)

```
uv pip install --python .venv\Scripts\python.exe pyinstaller
.venv\Scripts\python.exe -m PyInstaller --noconfirm --onefile --windowed ^
    --name "Manga Bubble Cleaner" --icon assets\logo.ico ^
    --add-data "assets;assets" --collect-all rapidocr_onnxruntime gui_app.py
```

El ejecutable queda en `dist\Manga Bubble Cleaner.exe` con el logo incrustado.
(`--collect-all rapidocr_onnxruntime` empaqueta los modelos OCR de chino/inglés
para que el OCR funcione también dentro del .exe, 100% offline.)

**El .exe es 100% independiente**: incluye Python, Tkinter, OpenCV, NumPy y Pillow.
Copialo a cualquier carpeta o PC y ejecutalo con doble clic: no requiere Python,
ni la carpeta del proyecto, ni el archivo `.bat`.

## Donaciones

La app incluye un botón **"♥ Donar"** que abre un enlace de donación (la app no
bloquea ninguna función). Para configurar tu enlace **no hace falta recompilar**:
creá un archivo `donacion.txt` junto al `.exe` y pegá dentro la URL (por ejemplo
`https://paypal.me/tunombre` o un link de Ko-fi). Si el archivo no existe, el
botón te avisa cómo configurarlo.

## Extraer texto (OCR) para traducción

Antes de limpiar los globos, la app puede **detectar el texto de cada globo** y
mostrarlo en el panel inferior, listo para traducir en un paso posterior:

- En la barra **"Extraer texto (OCR)"** activá el checkbox (viene activado) y
  elegí el idioma del texto: `auto` (chino+inglés, modelos incluidos), o
  `ko`/`ja`/`zh`/`en`.
- El texto se guarda en el archivo `_texto.txt` junto a cada página cuando
  procesás una carpeta, y en la GUI podés **Copiar** o **Guardar texto...**.
- Usa **RapidOCR** (offline). El modelo de coreano/japonés extra NO viene
  incluido: descargalo de los [releases de RapidOCR](https://github.com/RapidAI/RapidOCR/releases)
  y ponelo en una carpeta `models/` junto a la app con estos nombres:
  `ko_rec.onnx`, `ja_rec.onnx`, `zh_rec.onnx` o `en_rec.onnx`.
- Si el motor no está instalado, ejecutá:
  `uv pip install --python .venv\Scripts\python.exe rapidocr-onnxruntime`.

La **traducción** automática del texto extraído es el siguiente paso planificado.

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