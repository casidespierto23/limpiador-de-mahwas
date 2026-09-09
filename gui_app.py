#!/usr/bin/env python3
"""
Manga Bubble Cleaner — Interfaz gráfica de escritorio

Requiere: Python 3.8+, OpenCV y Pillow. tkinter viene incluido con Python.
Uso: python gui_app.py
"""

import queue
import sys
import threading
import tkinter as tk
import webbrowser
from tkinter import ttk, filedialog, messagebox

import cv2
import numpy as np
from pathlib import Path
from PIL import Image, ImageTk

from app import MangaBubbleCleaner

ALLOWED_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.webp', '.bmp', '.tif', '.tiff'}

# Enlace de donación por defecto (se puede cambiar con un archivo "donacion.txt"
# junto al .exe, sin necesidad de recompilar).
DONATION_URL = ''
DONATION_FILE = 'donacion.txt'


def _donation_url():
    if getattr(sys, 'frozen', False):
        base = Path(sys.executable).parent
    else:
        base = Path(__file__).resolve().parent
    try:
        url = (base / DONATION_FILE).read_text(encoding='utf-8-sig').strip()
        if url:
            return url
    except OSError:
        pass
    return DONATION_URL


def _assets_dir():
    """Directorio de assets: carpeta real o la incrustada en el .exe (PyInstaller)."""
    base = getattr(sys, '_MEIPASS', None)
    if base:
        return Path(base) / 'assets'
    return Path(__file__).resolve().parent / 'assets'


class ZoomableCanvas(ttk.Frame):
    """Canvas con scrollbars y soporte de zoom para mostrar imágenes."""

    def __init__(self, master, **kwargs):
        super().__init__(master, **kwargs)
        self.canvas = tk.Canvas(self, highlightthickness=0, background='#2e2e2e')
        self.xbar = ttk.Scrollbar(self, orient='horizontal', command=self.canvas.xview)
        self.ybar = ttk.Scrollbar(self, orient='vertical', command=self.canvas.yview)
        self.canvas.configure(xscrollcommand=self.xbar.set, yscrollcommand=self.ybar.set)

        self.canvas.grid(row=0, column=0, sticky='nsew')
        self.ybar.grid(row=0, column=1, sticky='ns')
        self.xbar.grid(row=1, column=0, sticky='ew')
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)

        self._np_image = None
        self._scale = 1.0
        self._render_scale = 1.0
        self._photo = None
        self._item = None

        self.canvas.bind('<Configure>', lambda e: self._render())
        self.canvas.bind('<MouseWheel>', self._on_mousewheel)

    @property
    def scale(self):
        return self._scale

    def canvas_to_image(self, cx, cy):
        """Convierte coords del widget canvas a píxeles de la imagen (o None)."""
        if self._np_image is None or self._item is None or self._render_scale <= 0:
            return None
        ix, iy = self.canvas.coords(self._item)
        px = int(round((self.canvas.canvasx(cx) - ix) / self._render_scale))
        py = int(round((self.canvas.canvasy(cy) - iy) / self._render_scale))
        h, w = self._np_image.shape[:2]
        if not (0 <= px < w and 0 <= py < h):
            return None
        return px, py

    def image_to_canvas(self, px, py):
        """Convierte píxeles de imagen a coords (scrollregion) del canvas."""
        if self._item is None:
            return px, py
        ix, iy = self.canvas.coords(self._item)
        return ix + px * self._render_scale, iy + py * self._render_scale

    def set_image(self, np_bgr, scale=None):
        """Muestra la imagen; si scale es None, se ajusta a la ventana."""
        self._np_image = np_bgr
        if scale is not None:
            self._scale = scale
        self._render()

    def fit(self):
        self._scale = 0.0  # auto
        self._render()

    def zoom_in(self):
        self._scale = max(0.05, (self._scale or 1.0) * 1.25)
        self._render()

    def zoom_out(self):
        self._scale = max(0.05, (self._scale or 1.0) / 1.25)
        self._render()

    def actual_size(self):
        self._scale = 1.0
        self._render()

    def clear(self):
        self._np_image = None
        self.canvas.delete('all')

    def _on_mousewheel(self, event):
        if self._np_image is None:
            return
        self.canvas.yview_scroll(int(-event.delta / 120), 'units')

    def _render(self):
        if self._np_image is None:
            return
        h, w = self._np_image.shape[:2]
        scale = self._scale
        if scale <= 0:  # modo auto
            cw = max(self.canvas.winfo_width(), 50)
            ch = max(self.canvas.winfo_height(), 50)
            scale = min(cw / w, ch / h)
        self._render_scale = scale
        tw, th = max(1, int(round(w * scale))), max(1, int(round(h * scale)))
        rgb = cv2.cvtColor(self._np_image, cv2.COLOR_BGR2RGB)
        pil = Image.fromarray(rgb).resize((tw, th), Image.LANCZOS)
        self._photo = ImageTk.PhotoImage(pil)
        self.canvas.delete('all')
        x0, y0 = self.canvas.canvasx(0), self.canvas.canvasy(0)
        self._item = self.canvas.create_image(x0, y0, image=self._photo, anchor='nw')
        self.canvas.configure(scrollregion=(0, 0, tw, th))


class MangaCleanerApp:
    def __init__(self, root):
        self.root = root
        self.root.title('Manga Bubble Cleaner — Escritorio')
        self.root.geometry('1280x800')
        self.root.minsize(980, 640)

        self.cleaner = MangaBubbleCleaner()

        self.original = None
        self.result = None
        self.detection_overlay = None
        self.current_path = None
        self.image_list = []
        self.index = 0
        self._busy = False
        self._fit = True
        self._scale = 1.0
        self._gui_queue = queue.Queue()
        self._undo_stack = []
        self._auto_result = None
        self._drawing = None
        self._brush_pts = []
        self._brush_dots = []
        self.var_brush = tk.IntVar(value=25)

        self._build_ui()
        self._set_app_icon()
        self._update_nav_state()
        self.root.after(100, self._poll_queue)

    def _set_app_icon(self):
        assets = _assets_dir()
        ico = assets / 'logo.ico'
        png = assets / 'logo.png'
        try:
            if ico.exists():
                self.root.iconbitmap(str(ico))
        except tk.TclError:
            pass
        try:
            if png.exists():
                img = Image.open(png).resize((64, 64), Image.Resampling.BICUBIC)
                self._icon = ImageTk.PhotoImage(img)
                self.root.iconphoto(True, self._icon)
        except Exception:
            pass

    # ------------------------------------------------------------------ UI
    def _build_ui(self):
        # Barra de herramientas
        toolbar = ttk.Frame(self.root, padding=(8, 6))
        toolbar.pack(side='top', fill='x')

        ttk.Button(toolbar, text='Abrir imagen', command=self.open_image).pack(side='left')
        ttk.Button(toolbar, text='Abrir carpeta', command=self.open_folder).pack(side='left', padx=(6, 0))
        ttk.Button(toolbar, text='Anterior', command=self.prev_image).pack(side='left', padx=(12, 0))
        ttk.Button(toolbar, text='Siguiente', command=self.next_image).pack(side='left', padx=(4, 0))
        self.nav_label = ttk.Label(toolbar, text='')
        self.nav_label.pack(side='left', padx=(8, 0))

        ttk.Separator(toolbar, orient='vertical').pack(side='left', fill='y', padx=12)
        self.process_btn = ttk.Button(toolbar, text='Procesar página',
                                      command=self.process_current)
        self.process_btn.pack(side='left')
        ttk.Button(toolbar, text='Guardar como...', command=self.save_image).pack(side='left', padx=(6, 0))
        ttk.Button(toolbar, text='Procesar carpeta...', command=self.process_folder).pack(side='left', padx=(6, 0))

        ttk.Separator(toolbar, orient='vertical').pack(side='left', fill='y', padx=12)
        ttk.Button(toolbar, text='♥ Donar', command=self.donate).pack(side='left')

        # Panel de controles
        panel = ttk.LabelFrame(self.root, text='Ajustes', padding=8)
        panel.pack(side='left', fill='y', padx=8, pady=6)

        self.var_thresh = tk.IntVar(value=200)
        ttk.Label(panel, text='Umbral de blancura').pack(anchor='w')
        ttk.Scale(panel, from_=120, to=255, variable=self.var_thresh,
                  command=lambda v: self.lbl_thresh.config(text=str(int(float(v))))).pack(fill='x', pady=(2, 6))
        self.lbl_thresh = ttk.Label(panel, text='200')
        self.lbl_thresh.pack(anchor='w')

        self.var_area = tk.IntVar(value=1500)
        ttk.Label(panel, text='Área mínima del globo').pack(anchor='w', pady=(6, 0))
        ttk.Scale(panel, from_=100, to=20000, variable=self.var_area,
                  command=lambda v: self.lbl_area.config(text=str(int(float(v))))).pack(fill='x', pady=(2, 6))
        self.lbl_area = ttk.Label(panel, text='1500')
        self.lbl_area.pack(anchor='w')

        self.var_radius = tk.IntVar(value=3)
        ttk.Label(panel, text='Radio de inpainting').pack(anchor='w', pady=(6, 0))
        ttk.Scale(panel, from_=1, to=12, variable=self.var_radius,
                  command=lambda v: self.lbl_radius.config(text=str(int(float(v))))).pack(fill='x', pady=(2, 6))
        self.lbl_radius = ttk.Label(panel, text='3')
        self.lbl_radius.pack(anchor='w')

        self.var_auto = tk.BooleanVar(value=True)
        ttk.Checkbutton(panel, text='Limpiar automáticamente al abrir',
                        variable=self.var_auto).pack(anchor='w', pady=(8, 0))

        self.var_text = tk.BooleanVar(value=False)
        ttk.Checkbutton(panel, text='Limpiar texto sin globo (avanzado)',
                        variable=self.var_text).pack(anchor='w', pady=(4, 0))

        self.var_view = tk.StringVar(value='Resultado')
        ttk.Label(panel, text='Vista derecha').pack(anchor='w', pady=(6, 0))
        view = ttk.Combobox(panel, textvariable=self.var_view, state='readonly',
                            values=('Resultado', 'Detección'))
        view.pack(fill='x')
        view.bind('<<ComboboxSelected>>', lambda e: self._refresh_displays())

        ttk.Separator(panel).pack(fill='x', pady=10)

        manual = ttk.LabelFrame(panel, text='Trabajo manual', padding=8)
        manual.pack(fill='x', pady=(6, 0))

        self.var_tool = tk.StringVar(value='none')
        tools_row = ttk.Frame(manual)
        tools_row.pack(fill='x')
        self._tool_buttons = {}
        for label, value in (('Ninguno', 'none'), ('Pincel', 'brush'), ('Rectángulo', 'rect')):
            b = tk.Button(tools_row, text=label, width=9, relief='raised',
                          command=lambda v=value: self._set_tool(v))
            b.pack(side='left', padx=(0, 4))
            self._tool_buttons[value] = b

        br_row = ttk.Frame(manual)
        br_row.pack(fill='x', pady=(8, 0))
        ttk.Label(br_row, text='Tamaño del pincel').pack(side='left')
        self.brush_preview = tk.Canvas(br_row, width=32, height=24,
                                       bg='SystemButtonFace', highlightthickness=0)
        self.brush_preview.pack(side='right')
        self.lbl_brush_val = ttk.Label(br_row, text='25 px')
        self.lbl_brush_val.pack(side='right', padx=(0, 6))
        ttk.Scale(manual, from_=5, to=150, variable=self.var_brush,
                  command=self._on_brush_change).pack(fill='x', pady=(2, 0))

        self.help_label = ttk.Label(manual, text='Elegí una herramienta para retocar.', 
                                    foreground='#555555', wraplength=220)
        self.help_label.pack(fill='x', pady=(6, 0))

        action_row = ttk.Frame(manual)
        action_row.pack(fill='x', pady=(8, 0))
        self.undo_btn = ttk.Button(action_row, text='Deshacer', command=self.undo_manual,
                                   state='disabled')
        self.undo_btn.pack(side='left')
        self.reset_btn = ttk.Button(action_row, text='Reiniciar', command=self.reset_manual,
                                    state='disabled')
        self.reset_btn.pack(side='left', padx=(4, 0))

        ttk.Separator(panel).pack(fill='x', pady=10)

        ttk.Label(panel, text='Zoom').pack(anchor='w')
        zoom_row = ttk.Frame(panel)
        zoom_row.pack(fill='x', pady=(4, 0))
        ttk.Button(zoom_row, text='-', width=3, command=self.zoom_out).pack(side='left')
        ttk.Button(zoom_row, text='+', width=3, command=self.zoom_in).pack(side='left', padx=4)
        ttk.Button(zoom_row, text='Ajustar', command=self.zoom_fit).pack(side='left')
        ttk.Button(zoom_row, text='100%', command=self.zoom_100).pack(side='left', padx=(4, 0))

        # Área de imágenes
        images = ttk.PanedWindow(self.root, orient='horizontal')
        images.pack(side='left', fill='both', expand=True, padx=(0, 8), pady=6)

        left_frame = ttk.Frame(images)
        self.original_canvas = ZoomableCanvas(left_frame)
        self.original_canvas.pack(fill='both', expand=True)
        ttk.Label(left_frame, text='ORIGINAL', anchor='center').pack(fill='x')
        images.add(left_frame, weight=1)

        right_frame = ttk.Frame(images)
        self.result_canvas = ZoomableCanvas(right_frame)
        self.result_canvas.pack(fill='both', expand=True)
        ttk.Label(right_frame, text='PROCESADA / DETECCIÓN', anchor='center').pack(fill='x')
        images.add(right_frame, weight=1)

        cv = self.result_canvas.canvas
        cv.bind('<ButtonPress-1>', self._on_canvas_press)
        cv.bind('<B1-Motion>', self._on_canvas_drag)
        cv.bind('<ButtonRelease-1>', self._on_canvas_release)
        cv.bind('<Motion>', self._on_canvas_motion)
        cv.bind('<Leave>', lambda e: self._hide_hover())
        cv.bind('<Escape>', lambda e: self._cancel_drawing())

        self._hover = None
        self._tool_buttons['none'].config(relief='sunken', bg='#d7e6f5')

        # Barra de estado
        self.status = ttk.Label(self.root, text='Listo. Abre una imagen para empezar.',
                                anchor='w', padding=(8, 4), relief='sunken')
        self.status.pack(side='bottom', fill='x')

    # ------------------------------------------------------------- acciones
    def open_image(self):
        path = filedialog.askopenfilename(
            title='Abrir imagen',
            filetypes=[('Imágenes', '*.png *.jpg *.jpeg *.webp *.bmp *.tif *.tiff'),
                       ('Todos los archivos', '*.*')])
        if not path:
            return
        self.image_list = [Path(path)]
        self.index = 0
        self._load_current()

    def open_folder(self):
        folder = filedialog.askdirectory(title='Abrir carpeta de páginas')
        if not folder:
            return
        folder = Path(folder)
        files = [p for p in sorted(folder.iterdir()) if p.suffix.lower() in ALLOWED_EXTENSIONS]
        if not files:
            messagebox.showwarning('Sin imágenes',
                                   f'No se encontraron imágenes en:\n{folder}')
            return
        self.image_list = files
        self.index = 0
        self._load_current()

    def prev_image(self):
        if self.image_list:
            self.index = (self.index - 1) % len(self.image_list)
            self._load_current()

    def next_image(self):
        if self.image_list:
            self.index = (self.index + 1) % len(self.image_list)
            self._load_current()

    def _load_current(self):
        path = self.image_list[self.index]
        try:
            with Image.open(path) as im:
                self.original = cv2.cvtColor(np.array(im.convert('RGB')), cv2.COLOR_RGB2BGR)
        except Exception as e:
            messagebox.showerror('Error', f'No se pudo cargar {path}:\n{e}')
            return
        self.current_path = path
        self.result = None
        self.detection_overlay = None
        self._undo_stack = []
        self._auto_result = None
        self._cancel_drawing()
        self._update_undo_state()
        self._fit = True
        self._refresh_displays()
        self._update_nav_state()
        self.set_status(f'Cargada: {path.name}  ({self.original.shape[1]}x{self.original.shape[0]})')
        if self.var_auto.get():
            self.process_current()

    def _update_nav_state(self):
        if self.image_list:
            self.nav_label.config(text=f'{self.index + 1}/{len(self.image_list)}')

    def _right_image(self):
        if self.var_view.get() == 'Detección' and self.detection_overlay is not None:
            return self.detection_overlay
        return self.result

    def _refresh_displays(self):
        if self.original is None:
            return
        if self._fit:
            self.original_canvas.set_image(self.original)
            self.result_canvas.set_image(self._right_image())
        else:
            self.original_canvas.set_image(self.original, scale=self._scale)
            self.result_canvas.set_image(self._right_image(), scale=self._scale)

    def zoom_in(self):
        self._fit = False
        self._scale = max(0.05, self._scale * 1.25)
        self._refresh_displays()

    def zoom_out(self):
        self._fit = False
        self._scale = max(0.05, self._scale / 1.25)
        self._refresh_displays()

    def zoom_fit(self):
        self._fit = True
        self._refresh_displays()

    def zoom_100(self):
        self._fit = False
        self._scale = 1.0
        self._refresh_displays()

    # ------------------------------------------------------------- proceso
    def set_status(self, text):
        self.status.config(text=text)

    def _post(self, callback):
        """Encola una tarea para ejecutarla en el hilo principal (thread-safe)."""
        self._gui_queue.put(callback)

    def _poll_queue(self):
        try:
            while True:
                callback = self._gui_queue.get_nowait()
                callback()
        except queue.Empty:
            pass
        self.root.after(100, self._poll_queue)

    def _params(self):
        return {
            'white_threshold': self.var_thresh.get(),
            'min_contour_area': self.var_area.get(),
            'require_convex': False,
            'radius': self.var_radius.get(),
            'clean_free_text': self.var_text.get(),
        }

    def process_current(self):
        if self.original is None:
            messagebox.showinfo('Aviso', 'Primero abre una imagen.')
            return
        if self._busy:
            return
        self._set_busy(True)
        params = self._params()
        image = self.original.copy()
        self.set_status('Procesando página...')

        def work():
            try:
                bubbles, result = self._detect_and_clean(image, params)
                debug = self._build_detection_view(image, bubbles)
                self._post(lambda: self._on_processed(bubbles, result, debug))
            except Exception as e:
                self._post(lambda: self._on_error(str(e)))

        threading.Thread(target=work, daemon=True).start()

    def _detect_and_clean(self, image, params):
        detections = self.cleaner.detect_bubbles_with_masks(
            image,
            white_threshold=params['white_threshold'],
            min_contour_area=params['min_contour_area'],
            max_contour_area=params.get('max_contour_area'),
            require_convex=params['require_convex'],
        )
        bubbles = [box for box, _ in detections]
        masks = [mask for _, mask in detections]
        result = image.copy()
        for (x1, y1, x2, y2), m in zip(bubbles, masks):
            result = self.cleaner.inpaint_bubble(
                result, x1, y1, x2, y2, radius=params['radius'], bubble_mask=m)
        if params.get('clean_free_text'):
            rows = self.cleaner.find_text_rows(result)
            result = self.cleaner.inpaint_free_text(
                result, rows, radius=params['radius'])
        return bubbles, result

    @staticmethod
    def _build_detection_view(image, bubbles):
        debug = image.copy()
        for i, (x1, y1, x2, y2) in enumerate(bubbles, 1):
            cv2.rectangle(debug, (x1, y1), (x2, y2), (0, 255, 0), 3)
            cv2.putText(debug, str(i), (x1 + 8, y1 + 30),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 255, 0), 2, cv2.LINE_AA)
        return debug

    def _on_processed(self, bubbles, result, debug):
        self._set_busy(False)
        self.result = result
        self._auto_result = result.copy()
        self._undo_stack.clear()
        self.detection_overlay = debug
        self.var_view.set('Resultado')
        self._refresh_displays()
        self._update_undo_state()
        self.set_status(f'Listo: {len(bubbles)} globos detectados y limpiados.')

    def _on_error(self, err):
        self._set_busy(False)
        messagebox.showerror('Error', f'Ocurrió un error:\n{err}')
        self.set_status('Error al procesar.')

    def _set_busy(self, busy):
        self._busy = busy
        self.process_btn.config(state='disabled' if busy else 'normal')
        if busy:
            self.root.config(cursor='watch')
        else:
            self.root.config(cursor='')

    # -------------------------------------------------- edición manual
    def _set_tool(self, value):
        self._cancel_drawing()
        self._hide_hover()
        self.var_tool.set(value)
        for key, b in self._tool_buttons.items():
            b.config(relief='sunken' if key == value else 'raised',
                     bg='#d7e6f5' if key == value else 'SystemButtonFace')
        cursor = 'crosshair' if value != 'none' else ''
        self.result_canvas.canvas.configure(cursor=cursor)
        hints = {
            'none': 'Elegí una herramienta para retocar la página tratada.',
            'brush': 'Pintá encima del texto; al soltar el botón se limpia esa zona.',
            'rect': 'Arrastrá para encerrar un globo o palabra y limpiar su texto.',
        }
        self.help_label.config(text=hints[value])
        self.brush_preview.configure(bg='SystemButtonFace' if value == 'brush'
                                     else '#e8e8e8')
        self._draw_brush_preview()

    def _on_brush_change(self, val):
        size = int(float(val))
        self.lbl_brush_val.config(text=f'{size} px')
        self._draw_brush_preview()
        if self._hover is not None:
            self._update_hover_radius()

    def _draw_brush_preview(self):
        cv2b = self.brush_preview
        cv2b.delete('all')
        size = self.var_brush.get()
        cx, cy = cv2b.winfo_reqwidth() / 2, 12
        r = min(70.0, size) / 150.0 * 11.0
        cv2b.create_oval(cx - r, cy - r, cx + r, cy + r,
                         outline='#c03030', width=2, fill='#ff8888')

    def _on_canvas_motion(self, event):
        tool = self.var_tool.get()
        if tool != 'brush' or self.result is None or self._busy or self._drawing:
            self._hide_hover()
            return
        p = self.result_canvas.canvas_to_image(event.x, event.y)
        if p is None:
            self._hide_hover()
            return
        cv = self.result_canvas.canvas
        r = max(1.0, self.var_brush.get() * self.result_canvas._render_scale / 2)
        sx, sy = cv.canvasx(event.x), cv.canvasy(event.y)
        if self._hover is None:
            self._hover = cv.create_oval(sx - r, sy - r, sx + r, sy + r,
                                         outline='#e04040', width=1, dash=(3, 2))
        else:
            cv.coords(self._hover, sx - r, sy - r, sx + r, sy + r)

    def _update_hover_radius(self):
        if self._hover is None:
            return
        cv = self.result_canvas.canvas
        r = max(1.0, self.var_brush.get() * self.result_canvas._render_scale / 2)
        x0, y0, _, _ = cv.coords(self._hover)
        cv.coords(self._hover, x0, y0, x0 + 2 * r, y0 + 2 * r)

    def _hide_hover(self):
        if self._hover is not None:
            self.result_canvas.canvas.delete(self._hover)
            self._hover = None

    def _on_canvas_press(self, event):
        self._brush_dots = []
        self._sel_item = None
        self._sel_text = None
        self._sel_origin = None
        tool = self.var_tool.get()
        if tool == 'none' or self.result is None or self._busy:
            return
        cv = self.result_canvas.canvas
        if tool == 'rect':
            self._sel_origin = (event.x, event.y)
            sx, sy = cv.canvasx(event.x), cv.canvasy(event.y)
            self._sel_item = cv.create_rectangle(
                sx, sy, sx, sy, outline='#c02020', width=2, dash=(5, 3),
                fill='#ff9999', stipple='gray50')
            self._sel_text = cv.create_text(
                sx + 6, sy - 10, text='8×8', anchor='nw',
                fill='#b00000', font=('Segoe UI', 8, 'bold'))
        elif tool == 'brush':
            p = self.result_canvas.canvas_to_image(event.x, event.y)
            if p:
                self._brush_pts = [p]
                self._brush_dots = [self._draw_brush_dot(p)]
                self._drawing = True
            else:
                self._drawing = False

    def _on_canvas_drag(self, event):
        cv = self.result_canvas.canvas
        tool = self.var_tool.get()
        if self.result is None or self._busy:
            return
        if tool == 'rect' and self._sel_item is not None:
            sx, sy = cv.canvasx(event.x), cv.canvasy(event.y)
            ox, oy = cv.canvasx(self._sel_origin[0]), cv.canvasy(self._sel_origin[1])
            cv.coords(self._sel_item, ox, oy, sx, sy)
            p0 = self.result_canvas.canvas_to_image(self._sel_origin[0], self._sel_origin[1])
            p1 = self.result_canvas.canvas_to_image(event.x, event.y)
            if self._sel_text is not None and p0 and p1:
                wt = abs(p1[0] - p0[0]) + 1
                ht = abs(p1[1] - p0[1]) + 1
                cv.itemconfig(self._sel_text, text=f'{wt}×{ht}')
                tx = (ox + sx) / 2
                ty = min(oy, sy) - 12
                cv.coords(self._sel_text, tx, ty)
        elif tool == 'brush' and self._drawing:
            p = self.result_canvas.canvas_to_image(event.x, event.y)
            if p:
                last = self._brush_pts[-1]
                r = self.var_brush.get()
                if (p[0] - last[0]) ** 2 + (p[1] - last[1]) ** 2 > (r / 4) ** 2:
                    self._brush_pts.append(p)
                    self._brush_dots.append(self._draw_brush_dot(p))

    def _draw_brush_dot(self, p):
        cv = self.result_canvas.canvas
        r_px = max(1.0, self.var_brush.get() * self.result_canvas._render_scale / 2)
        sx, sy = self.result_canvas.image_to_canvas(p[0], p[1])
        return cv.create_oval(sx - r_px, sy - r_px, sx + r_px, sy + r_px,
                              outline='#a02020', width=1,
                              fill='#ff5555', stipple='gray50')

    def _on_canvas_release(self, event):
        tool = self.var_tool.get()
        if self.result is None or self._busy:
            self._cancel_drawing()
            return
        if tool == 'rect' and self._sel_item is not None:
            p0 = self.result_canvas.canvas_to_image(self._sel_origin[0], self._sel_origin[1])
            p1 = self.result_canvas.canvas_to_image(event.x, event.y)
            self._cancel_drawing()
            if p0 and p1:
                x1, y1 = min(p0[0], p1[0]), min(p0[1], p1[1])
                x2, y2 = max(p0[0], p1[0]), max(p0[1], p1[1])
                if x2 - x1 >= 8 and y2 - y1 >= 8:
                    self._manual_rect_clean(x1, y1, x2, y2)
        elif tool == 'brush' and getattr(self, '_brush_pts', None):
            pts = list(self._brush_pts)
            self._brush_pts = []
            self._drawing = False
            if pts:
                self._manual_brush_clean(pts, self.var_brush.get())

    def _push_undo(self):
        if self.result is not None:
            self._undo_stack.append(self.result.copy())
            if len(self._undo_stack) > 10:
                del self._undo_stack[0]

    def _update_undo_state(self):
        n = len(self._undo_stack)
        has_auto = self._auto_result is not None
        self.undo_btn.config(state='normal' if n else 'disabled',
                             text=f'Deshacer ({n})' if n else 'Deshacer')
        self.reset_btn.config(state='normal' if has_auto and n else 'disabled')

    def _apply_manual_edit(self, new_result, changed, label):
        self._push_undo()
        self.result = new_result
        self.var_view.set('Resultado')
        self._refresh_displays()
        self._update_undo_state()
        if changed:
            self.set_status(f'Limpiado con {label}: {changed} px editados.')
        else:
            self.set_status(f'{label}: no se encontró nada que limpiar en esa zona.')

    def _manual_rect_clean(self, x1, y1, x2, y2):
        """Limpia el texto dentro del rectángulo elegido (burbuja)."""
        h, w = self.result.shape[:2]
        x1, y1 = max(0, x1), max(0, y1)
        x2, y2 = min(w - 1, x2), min(h - 1, y2)
        mask = np.zeros((h, w), dtype=np.uint8)
        mask[y1:y2 + 1, x1:x2 + 1] = 255
        radius = self.var_radius.get()
        new_result = self.cleaner.inpaint_bubble(
            self.result, x1, y1, x2, y2, radius=radius, bubble_mask=mask)
        changed = int((np.abs(new_result.astype(int) - self.result.astype(int)).sum(axis=2) > 40).sum())
        self._apply_manual_edit(new_result, changed, f'rectángulo {x2 - x1 + 1}×{y2 - y1 + 1}')

    def _manual_brush_clean(self, points, brush_radius):
        """Limpia los trazos pintados con el pincel."""
        h, w = self.result.shape[:2]
        mask = np.zeros((h, w), dtype=np.uint8)
        for (px, py) in points:
            cv2.circle(mask, (px, py), max(1, brush_radius // 2), 255, -1)
        mask = cv2.dilate(mask, np.ones((5, 5), np.uint8), iterations=1)
        new_result = cv2.inpaint(self.result, mask, self.var_radius.get(), cv2.INPAINT_TELEA)
        changed = int((np.abs(new_result.astype(int) - self.result.astype(int)).sum(axis=2) > 40).sum())
        self._apply_manual_edit(new_result, changed, f'el pincel ({len(points)} puntos)')

    def undo_manual(self):
        if not self._undo_stack:
            self.set_status('No hay ediciones manuales que deshacer.')
            return
        self.result = self._undo_stack.pop()
        self.var_view.set('Resultado')
        self._refresh_displays()
        self._update_undo_state()
        self.set_status(f'Última edición deshecha. Quedan {len(self._undo_stack)} en el historial.')

    def reset_manual(self):
        if self._auto_result is None:
            return
        self.result = self._auto_result.copy()
        self._undo_stack.clear()
        self.var_view.set('Resultado')
        self._refresh_displays()
        self._update_undo_state()
        self.set_status('Ediciones manuales descartadas. Se restauró el resultado automático.')

    def _cancel_drawing(self):
        if getattr(self, '_brush_dots', None):
            for it in self._brush_dots:
                self.result_canvas.canvas.delete(it)
            self._brush_dots = []
        if getattr(self, '_sel_item', None):
            self.result_canvas.canvas.delete(self._sel_item)
            self._sel_item = None
        if getattr(self, '_sel_text', None):
            self.result_canvas.canvas.delete(self._sel_text)
            self._sel_text = None
        self._hide_hover()
        self._sel_origin = None
        self._brush_pts = []

    # ------------------------------------------------------------- donación
    def donate(self):
        url = _donation_url()
        if not url:
            messagebox.showinfo(
                'Donación',
                'Aún no configuraste tu enlace de donación.\n\n'
                'Creá un archivo "donacion.txt" junto a la app y pegá dentro '
                'el link (PayPal.me, Ko-fi, BuyMeACoffee, etc.). '
                'El botón "Donar" lo abrirá automáticamente.')
            return
        webbrowser.open(url)
        self.set_status(f'Abriendo enlace de donación: {url}')

    # ------------------------------------------------------------- guardar
    def save_image(self):
        if self.result is None:
            messagebox.showinfo('Aviso', 'Procesa una página antes de guardar.')
            return
        default = self.current_path.stem + '_cleaned.png' if self.current_path else 'cleaned.png'
        path = filedialog.asksaveasfilename(
            title='Guardar imagen procesada',
            defaultextension='.png',
            initialfile=default,
            filetypes=[('PNG', '*.png'), ('JPEG', '*.jpg'), ('WEBP', '*.webp')])
        if not path:
            return
        cv2.imwrite(path, self.result)
        self.set_status(f'Guardada: {path}')

    def process_folder(self):
        if self._busy:
            return
        folder = filedialog.askdirectory(title='Carpeta con las páginas')
        if not folder:
            return
        folder = Path(folder)
        files = [p for p in sorted(folder.iterdir()) if p.suffix.lower() in ALLOWED_EXTENSIONS]
        if not files:
            messagebox.showwarning('Sin imágenes', f'No hay imágenes en:\n{folder}')
            return
        out_folder = filedialog.askdirectory(title='Carpeta donde guardar el resultado')
        if not out_folder:
            return
        out_folder = Path(out_folder)
        params = self._params()
        self._set_busy(True)

        def work():
            total = len(files)
            errors = []
            for idx, p in enumerate(files, 1):
                self._post(lambda i=idx, n=total, name=p.name:
                           self.set_status(f'Procesando {i}/{n}: {name}'))
                try:
                    with Image.open(p) as im:
                        page = cv2.cvtColor(np.array(im.convert('RGB')), cv2.COLOR_RGB2BGR)
                    _, cleaned = self._detect_and_clean(page, params)
                    out = out_folder / (p.stem + '_cleaned' + p.suffix.lower())
                    cv2.imwrite(str(out), cleaned)
                except Exception as e:
                    errors.append(f'{p.name}: {e}')
            msg = f'Procesadas {total - len(errors)}/{total} imágenes.'
            if errors:
                msg += f'\nErrores ({len(errors)}):\n' + '\n'.join(errors[:5])
            self._post(lambda: self._on_batch_done(msg))

        threading.Thread(target=work, daemon=True).start()

    def _on_batch_done(self, msg):
        self._set_busy(False)
        messagebox.showinfo('Proceso por lotes', msg)
        self.set_status(msg.splitlines()[0])


def main():
    root = tk.Tk()
    MangaCleanerApp(root)
    root.mainloop()


if __name__ == '__main__':
    main()