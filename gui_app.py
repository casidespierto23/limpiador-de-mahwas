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
from tkinter.scrolledtext import ScrolledText

import cv2
import math
import numpy as np
from pathlib import Path
from PIL import Image, ImageTk, ImageDraw

from app import MangaBubbleCleaner
from ocr import BubbleTextExtractor, transcript as ocr_transcript

ALLOWED_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.webp', '.bmp', '.tif', '.tiff'}

# Enlace de donación por defecto (se puede cambiar con un archivo "donacion.txt"
# junto al .exe, sin necesidad de recompilar).
DONATION_URL = ''
DONATION_FILE = 'donacion.txt'

# Paleta de la interfaz (arranca con los colores del logo).
COLORS = {
    'navy': '#0b3d46',       # cabecera
    'navy_text': '#a7d4d8',  # texto claro de la cabecera
    'teal': '#0f766e',       # acciones principales
    'teal_dark': '#0b5d56',
    'bg': '#eef2f5',         # fondo de la ventana
    'card': '#ffffff',
    'ink': '#1f2937',
    'muted': '#6b7280',
    'line': '#cbd5e1',
    'soft': '#d8ece9',       # herramienta activa / hover
}


def _gradient_pil(w, h, top, bottom):
    """Imagen con degradado vertical, para la cabecera y la bienvenida."""
    arr = np.zeros((h, w, 3), np.uint8)
    for y in range(h):
        t = y / max(1, h - 1)
        arr[y, :] = [int(top[i] + (bottom[i] - top[i]) * t) for i in range(3)]
    return Image.fromarray(arr)


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
        self._ocr = BubbleTextExtractor()

        self.original = None
        self.result = None
        self.detection_overlay = None
        self.ocr_results = None
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
        self._compare_pos = 0.5
        self._compare_dragging = False
        self._thumbs = []
        self._thumb_items = {}
        self._thumb_hl = None

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

    # ------------------------------------------------------- detalles vivos
    def _build_icons(self):
        """Iconos dibujados con PIL (nítidos a cualquier tamaño)."""
        S = 4
        size = 24

        def open_icon(d, b, f):
            x0, y0, x1, y1 = b
            r = (x1 - x0) // 20
            d.rounded_rectangle([x0 + 2*r, y0 + 2*r, x0 + 18*r, y0 + 18*r],
                                radius=3*r, outline=f, width=2*r)
            d.ellipse([x0 + 8*r, y0 + 4*r, x0 + 12*r, y0 + 8*r], outline=f, width=2*r)
            d.polygon([(x0 + 4*r, y0 + 16*r), (x0 + 10*r, y0 + 10*r),
                       (x0 + 16*r, y0 + 16*r)], fill=f)

        def folder_icon(d, b, f):
            x0, y0, x1, y1 = b
            r = (x1 - x0) // 20
            d.rectangle([x0 + 3*r, y0 + 6*r, x0 + 17*r, y0 + 18*r],
                        outline=f, width=2*r)
            d.line([(x0 + 4*r, y0 + 6*r), (x0 + 4*r, y0 + 3*r),
                    (x0 + 9*r, y0 + 3*r), (x0 + 11*r, y0 + 6*r)], fill=f, width=3*r)

        def wand_icon(d, b, f):
            x0, y0, x1, y1 = b
            r = (x1 - x0) // 20
            d.line([(x0 + 4*r, y0 + 17*r), (x0 + 13*r, y0 + 8*r)], fill=f, width=3*r)
            d.ellipse([x0 + 12*r, y0 + 5*r, x0 + 16*r, y0 + 9*r], fill=f)
            for (px, py, sz) in [(x0 + 17*r, y0 + 3*r, 3*r), (x0 + 5*r, y0 + 2*r, 2*r),
                                 (x0 + 16*r, y0 + 16*r, 2*r)]:
                d.ellipse([px - sz, py - sz, px + sz, py + sz], fill=f)

        def save_icon(d, b, f):
            x0, y0, x1, y1 = b
            r = (x1 - x0) // 20
            d.rounded_rectangle([x0 + 3*r, y0 + 3*r, x0 + 17*r, y0 + 17*r],
                                radius=2*r, outline=f, width=2*r)
            d.rectangle([x0 + 6*r, y0 + 3*r, x0 + 10*r, y0 + 8*r], fill=f)
            d.rounded_rectangle([x0 + 6*r, y0 + 10*r, x0 + 14*r, y0 + 17*r],
                                radius=2*r, outline=f, width=2*r)

        def heart_icon(d, b, f):
            x0, y0, x1, y1 = b
            r = (x1 - x0) // 20
            cx, cy = x0 + 10*r, y0 + 10*r
            s = 8*r
            d.polygon([(cx, cy + 9*r), (cx - 9*r, cy), (cx - 9*r, cy - 4*r),
                       (cx - 5*r, cy - 8*r), (cx, cy - 3*r), (cx + 5*r, cy - 8*r),
                       (cx + 9*r, cy - 4*r), (cx + 9*r, cy), (cx, cy + 9*r)], fill=f)

        def eye_icon(d, b, f):
            x0, y0, x1, y1 = b
            r = (x1 - x0) // 20
            d.ellipse([x0 + 2*r, y0 + 6*r, x0 + 18*r, y0 + 14*r],
                      outline=f, width=2*r)
            d.ellipse([x0 + 9*r, y0 + 8*r, x0 + 11*r, y0 + 12*r], fill=f)

        def build(fill):
            out = {}
            for name, fn in (('open', open_icon), ('folder', folder_icon),
                             ('wand', wand_icon), ('save', save_icon),
                             ('heart', heart_icon), ('eye', eye_icon)):
                im = Image.new('RGBA', (size*S, size*S), (0, 0, 0, 0))
                fn(ImageDraw.Draw(im), (0, 0, size*S, size*S), fill)
                out[name] = ImageTk.PhotoImage(im.resize((size, size), Image.LANCZOS),
                                               master=self.root)
            return out

        self.icons_dark = build((255, 255, 255, 255))          # sobre teal oscuro
        self.icons_teal = build((15, 118, 110, 255))           # sobre botones claros

    def _toast(self, text, kind='info', ms=2500):
        """Aviso flotante que aparece y desaparece solo (feedback amable)."""
        if getattr(self, '_toast_lbl', None) is None:
            self._toast_lbl = tk.Label(self.root, font=('Segoe UI', 10, 'bold'),
                                       padx=18, pady=9, bd=0,
                                       highlightthickness=1,
                                       highlightbackground=COLORS['line'])
        palette = {'ok': (COLORS['teal'], '#ffffff'),
                   'info': (COLORS['navy'], '#ffffff'),
                   'warn': ('#b45309', '#ffffff')}
        bg, fg = palette.get(kind, palette['info'])
        self._toast_lbl.config(text=text, bg=bg, fg=fg)
        self._toast_lbl.place(relx=0.5, rely=0.94, anchor='center')
        self._toast_lbl.lift()
        if getattr(self, '_toast_after', None):
            try:
                self.root.after_cancel(self._toast_after)
            except Exception:
                pass
        self._toast_after = self.root.after(ms, self._hide_toast)

    def _hide_toast(self):
        try:
            if getattr(self, '_toast_lbl', None):
                self._toast_lbl.place_forget()
        except tk.TclError:
            pass

    def _celebrate(self, bubbles):
        """Destellos de colores al terminar de limpiar. Puro alboroto visual."""
        try:
            cv = self.result_canvas.canvas
            sc = self.result_canvas
            colors = ('#ffd166', '#ef476f', '#06d6a0', '#118ab2', '#f78c6b', '#9b5de5')
            sparks = []
            for bx in (bubbles or [])[:8]:
                x1, y1, x2, y2 = bx
                cx, cy = (x1 + x2) / 2.0, (y1 + y2) / 2.0
                sx, sy = sc.image_to_canvas(cx, cy)
                burst = max(6.0, min(40.0, (x2 - x1) / 5.0))
                for _ in range(2):
                    ang = math.pi * (len(sparks) % 7) / 3.0 + 0.9
                    dx, dy = math.cos(ang), math.sin(ang)
                    sparks.append((cv.create_oval(sx-3, sy-3, sx+3, sy+3,
                                                  fill=colors[len(sparks) % len(colors)],
                                                  outline=''),
                                   sx, sy, dx, dy, burst))

            def anim(step=0):
                try:
                    for it, sx, sy, dx, dy, burst in sparks:
                        rr = 3 + step * 1.2
                        x = sx + dx * step * (burst / 8)
                        y = sy + dy * step * (burst / 8)
                        cv.coords(it, x-rr, y-rr, x+rr, y+rr)
                    if step < 14:
                        self.root.after(26, lambda: anim(step + 1))
                    else:
                        for it, *_ in sparks:
                            try:
                                cv.delete(it)
                            except tk.TclError:
                                pass
                except tk.TclError:
                    pass

            anim()
        except Exception:
            pass

    def _bind_tooltip(self, btn, text):
        def on_enter(event):
            self._hint_backup = self.status.cget('text')
            self.status.config(text=text, fg=COLORS['teal'])

        def on_leave(event):
            try:
                self.status.config(text=getattr(self, '_hint_backup', ''),
                                   fg=COLORS['muted'])
            except Exception:
                pass

        btn.bind('<Enter>', on_enter)
        btn.bind('<Leave>', on_leave)

    def _render_header_bg(self, event=None):
        if getattr(self, '_header_bg', None) is None:
            return
        if event is not None:
            w, h = event.width, event.height
        else:
            w = self._header_bg.winfo_width()
            h = self._header_bg.winfo_height()
        if w < 50:  # geometría aún no real; esperar el próximo Configure
            return
        if (w, h) == getattr(self, '_grad_size', (0, 0)):
            return
        self._grad_size = (w, h)
        self._header_grad = ImageTk.PhotoImage(
            _gradient_pil(w, h, (11, 58, 66), (15, 116, 108)), master=self.root)
        self._header_bg.config(image=self._header_grad)

    # ------------------------------------------------------------------ UI
    def _build_ui(self):
        self._apply_theme()
        self._build_header()
        self._build_toolbar()

        # Barra de estado (se empaqueta primero para quedar abajo del todo)
        self._build_status_bar()

        # Cuerpo: controles a la izquierda + visor principal
        body = ttk.Frame(self.root)
        body.pack(side='top', fill='both', expand=True, padx=8, pady=(4, 6))
        self._build_controls(body)
        self._build_viewer(body)

        # Panel de texto extraído (OCR), justo encima de la barra de estado
        self._build_ocr_panel()

        # Miniaturas de páginas (arriba de la barra de estado)
        self._build_thumbs()

        self._bind_shortcuts()
        self._hover = None
        self._set_tool('none')
        self._refresh_displays()
        self.set_status('Bienvenido. Abrí una página con "Abrir imagen..." o Ctrl+O.')
        self.root.after(450, lambda: self._toast('¡Bienvenido! Abrí tu primer manhwa y empezá a limpiar.'))

    def _apply_theme(self):
        style = ttk.Style(self.root)
        try:
            style.theme_use('clam')
        except tk.TclError:
            pass
        C = COLORS
        style.configure('.', background=C['bg'], foreground=C['ink'],
                        font=('Segoe UI', 10))
        style.configure('TFrame', background=C['bg'])
        style.configure('TLabel', background=C['bg'], foreground=C['ink'])
        style.configure('TLabelframe', background=C['bg'], bordercolor=C['line'],
                        relief='flat')
        style.configure('TLabelframe.Label', background=C['bg'], foreground=C['teal'],
                        font=('Segoe UI', 10, 'bold'))
        style.configure('TCheckbutton', background=C['bg'])
        style.configure('Accent.TButton', background=C['teal'], foreground='white',
                        borderwidth=0, padding=(16, 8), font=('Segoe UI', 10, 'bold'))
        style.map('Accent.TButton',
                  background=[('active', C['teal_dark']), ('pressed', C['teal_dark'])])
        style.configure('Soft.TButton', background='#ffffff', bordercolor=C['line'],
                        padding=(14, 7), focusthickness=0, font=('Segoe UI', 10))
        style.map('Soft.TButton', background=[('active', C['soft'])])
        style.configure('TCombobox', fieldbackground='#ffffff', background='#ffffff',
                        arrowcolor=C['ink'])
        style.configure('TProgressbar', troughcolor=C['line'], background=C['teal'])

    def _build_header(self):
        self._build_icons()
        C = COLORS
        header = tk.Frame(self.root, bg=C['navy'], height=64)
        header.pack(side='top', fill='x')
        header.pack_propagate(False)
        # Fondo con degradado (se re-renderiza al redimensionar)
        self._header_bg = tk.Label(header, bg=C['navy'])
        self._header_bg.place(x=0, y=0, relwidth=1, relheight=1)
        header.bind('<Configure>', self._render_header_bg)
        self._header_grad = None
        self._grad_size = (0, 0)

        self._header_logo = None
        try:
            img = Image.open(_assets_dir() / 'logo.png').resize((44, 44), Image.LANCZOS)
            self._header_logo = ImageTk.PhotoImage(img, master=self.root)
        except Exception:
            pass
        if self._header_logo is not None:
            tk.Label(header, image=self._header_logo, bg=C['navy']).pack(
                side='left', padx=(16, 8), pady=10)
        titles = tk.Frame(header, bg=C['navy'])
        titles.pack(side='left')
        tk.Label(titles, text='Manga Bubble Cleaner', bg=C['navy'], fg='white',
                 font=('Segoe UI', 15, 'bold')).pack(anchor='w')
        tk.Label(titles, text='Tu asistente para limpiar y traducir tus manhwas',
                 bg=C['navy'], fg=C['navy_text'], font=('Segoe UI', 9)).pack(anchor='w')
        donate_btn = ttk.Button(header, text='Donar', style='Accent.TButton',
                                image=self.icons_dark['heart'], compound='left',
                                command=self.donate)
        donate_btn.pack(side='right', padx=16, pady=13)
        self._bind_tooltip(donate_btn, 'Apoyá el proyecto con una donación')

    def _build_toolbar(self):
        tb = ttk.Frame(self.root, padding=(10, 8))
        tb.pack(side='top', fill='x')
        teal = self.icons_teal

        b = ttk.Button(tb, text='Abrir imagen...', style='Soft.TButton',
                       image=teal['open'], compound='left', command=self.open_image)
        b.pack(side='left')
        self._bind_tooltip(b, 'Abrí una imagen (Ctrl+O)')

        b = ttk.Button(tb, text='Abrir carpeta...', style='Soft.TButton',
                       image=teal['folder'], compound='left', command=self.open_folder)
        b.pack(side='left', padx=(6, 0))
        self._bind_tooltip(b, 'Abrí una carpeta de páginas (Ctrl+Shift+O)')

        ttk.Separator(tb, orient='vertical').pack(side='left', fill='y', padx=12)
        b = ttk.Button(tb, text='◀ Anterior', style='Soft.TButton',
                       command=self.prev_image)
        b.pack(side='left')
        self._bind_tooltip(b, 'Página anterior (Ctrl+←)')
        b = ttk.Button(tb, text='Siguiente ▶', style='Soft.TButton',
                       command=self.next_image)
        b.pack(side='left', padx=(4, 0))
        self._bind_tooltip(b, 'Página siguiente (Ctrl+→)')
        self.nav_label = ttk.Label(tb, text='', foreground=COLORS['muted'])
        self.nav_label.pack(side='left', padx=(8, 0))

        ttk.Separator(tb, orient='vertical').pack(side='left', fill='y', padx=12)
        self.process_btn = ttk.Button(tb, text='Procesar página',
                                      style='Accent.TButton',
                                      image=self.icons_dark['wand'],
                                      compound='left', command=self.process_current)
        self.process_btn.pack(side='left')
        self._bind_tooltip(self.process_btn,
                           'Analiza y limpia los globos de esta página (Ctrl+P)')

        b = ttk.Button(tb, text='Procesar carpeta...', style='Soft.TButton',
                       image=teal['folder'], compound='left',
                       command=self.process_folder)
        b.pack(side='left', padx=(6, 0))
        self._bind_tooltip(b, 'Limpia todas las páginas de la carpeta')

        b = ttk.Button(tb, text='Guardar imagen...', style='Soft.TButton',
                       image=teal['save'], compound='left', command=self.save_image)
        b.pack(side='left', padx=(6, 0))
        self._bind_tooltip(b, 'Guardá la página tratada (Ctrl+S)')

        ttk.Separator(tb, orient='vertical').pack(side='left', fill='y', padx=12)
        self.view_btn = ttk.Button(tb, text='Ocultar imagen', style='Soft.TButton',
                                   image=teal['eye'], compound='left',
                                   command=self._toggle_viewer)
        self.view_btn.pack(side='left')
        self._bind_tooltip(self.view_btn,
                           'Ocultá o mostrá el visor para trabajar sobre los controles sin distracciones')

    def _build_controls(self, parent):
        # Riel con botón para plegar/mostrar el panel (más espacio al visor)
        rail = ttk.Frame(parent, width=30)
        rail.pack(side='left', fill='y')
        self.panel_toggle = ttk.Button(rail, text='◀', width=2,
                                       command=self._toggle_panel)
        self.panel_toggle.pack(pady=(8, 0))

        # Panel con scroll vertical para que nunca se corten los controles
        self._panel_frame = ttk.Frame(parent, width=262)
        self._panel_frame.pack(side='left', fill='y')
        self._panel_frame.pack_propagate(False)
        self._panel_canvas = tk.Canvas(self._panel_frame, width=262,
                                       bg=COLORS['bg'], highlightthickness=0)
        vsbar = ttk.Scrollbar(self._panel_frame, orient='vertical',
                              command=self._panel_canvas.yview)
        self._panel_canvas.configure(yscrollcommand=vsbar.set)
        vsbar.pack(side='right', fill='y')
        self._panel_canvas.pack(side='left', fill='both', expand=True)
        inner = ttk.Frame(self._panel_canvas)
        self._panel_window = self._panel_canvas.create_window((0, 0), window=inner,
                                                              anchor='nw')
        inner.bind('<Configure>',
                   lambda e: self._panel_canvas.configure(scrollregion=self._panel_canvas.bbox('all')))
        self._panel_canvas.bind('<Configure>',
                                lambda e: self._panel_canvas.itemconfigure(self._panel_window,
                                                                           width=e.width))
        self.root.bind_all('<MouseWheel>', self._on_panel_wheel)
        panel = inner
        C = COLORS

        # Guía rápida compacta
        guide = ttk.LabelFrame(panel, text='Guía rápida', padding=6)
        guide.pack(fill='x', pady=(6, 0))
        ttk.Label(guide, foreground=C['muted'],
                  text='1 Abrir  ·  2 Procesar  ·  3 Copiar o Guardar').pack(anchor='w')

        # Limpieza automática
        det = ttk.LabelFrame(panel, text='Limpieza automática', padding=8)
        det.pack(fill='x', pady=(6, 0))
        self.var_auto = tk.BooleanVar(value=True)
        ttk.Checkbutton(det, text='Limpiar al abrir la página',
                        variable=self.var_auto).pack(anchor='w')
        self.var_text = tk.BooleanVar(value=False)
        ttk.Checkbutton(det, text='Borrar también el texto suelto (sin globo)',
                        variable=self.var_text).pack(anchor='w', pady=(4, 0))

        # Extracción de texto (OCR)
        ocr = ttk.LabelFrame(panel, text='Texto para traducir (OCR)', padding=8)
        ocr.pack(fill='x', pady=(6, 0))
        self.var_ocr = tk.BooleanVar(value=True)
        ttk.Checkbutton(ocr, text='Extraer el texto de los globos',
                        variable=self.var_ocr).pack(anchor='w')
        lang_row = ttk.Frame(ocr)
        lang_row.pack(fill='x', pady=(6, 0))
        ttk.Label(lang_row, text='Idioma:').pack(side='left')
        self.var_ocr_lang = tk.StringVar(value='auto')
        lang = ttk.Combobox(lang_row, textvariable=self.var_ocr_lang, state='readonly',
                            values=('auto', 'ko', 'ja', 'zh', 'en'), width=8)
        lang.pack(side='right')
        lang.bind('<<ComboboxSelected>>', lambda e: self._update_ocr_hint())

        # Retoque manual
        manual = ttk.LabelFrame(panel, text='Retoque manual', padding=8)
        manual.pack(fill='x', pady=(6, 0))
        self.var_tool = tk.StringVar(value='none')
        tools_row = ttk.Frame(manual)
        tools_row.pack(fill='x')
        self._tool_buttons = {}
        for label, value in (('Ninguno', 'none'), ('Pincel', 'brush'), ('Rectángulo', 'rect')):
            b = tk.Button(tools_row, text=label, width=9, relief='flat', bd=0,
                          bg='#ffffff', fg=COLORS['ink'],
                          activebackground=COLORS['soft'],
                          activeforeground=COLORS['teal'],
                          font=('Segoe UI', 10), cursor='hand2',
                          highlightthickness=1,
                          highlightbackground=COLORS['line'],
                          highlightcolor=COLORS['line'],
                          command=lambda v=value: self._set_tool(v))
            b.pack(side='left', padx=(0, 4))
            self._tool_buttons[value] = b
        br_row = ttk.Frame(manual)
        br_row.pack(fill='x', pady=(8, 0))
        ttk.Label(br_row, text='Tamaño del pincel').pack(side='left')
        self.brush_preview = tk.Canvas(br_row, width=34, height=26, bg='#ffffff',
                                       highlightthickness=0)
        self.brush_preview.pack(side='right')
        self.lbl_brush_val = ttk.Label(br_row, text='25 px')
        self.lbl_brush_val.pack(side='right', padx=(0, 6))
        ttk.Scale(manual, from_=5, to=150, variable=self.var_brush,
                  command=self._on_brush_change).pack(fill='x', pady=(2, 0))
        self.help_label = ttk.Label(manual, text='Elegí una herramienta para retocar.',
                                    foreground=COLORS['muted'], wraplength=230)
        self.help_label.pack(fill='x', pady=(6, 0))
        action_row = ttk.Frame(manual)
        action_row.pack(fill='x', pady=(8, 0))
        self.undo_btn = ttk.Button(action_row, text='Deshacer',
                                   command=self.undo_manual, state='disabled')
        self.undo_btn.pack(side='left')
        self.reset_btn = ttk.Button(action_row, text='Reiniciar',
                                    command=self.reset_manual, state='disabled')
        self.reset_btn.pack(side='left', padx=(4, 0))

        # Vista y zoom
        vista = ttk.LabelFrame(panel, text='Vista', padding=8)
        vista.pack(fill='x', pady=(6, 0))
        zoom_row = ttk.Frame(vista)
        zoom_row.pack(fill='x')
        ttk.Button(zoom_row, text='-', width=4, command=self.zoom_out).pack(side='left')
        ttk.Button(zoom_row, text='+', width=4, command=self.zoom_in).pack(side='left', padx=4)
        ttk.Button(zoom_row, text='Ajustar', command=self.zoom_fit).pack(side='left')
        ttk.Button(zoom_row, text='100%', command=self.zoom_100).pack(side='left', padx=(4, 0))
        self.var_view = tk.StringVar(value='Resultado')
        ttk.Label(vista, text='Vista derecha').pack(anchor='w', pady=(8, 2))
        view = ttk.Combobox(vista, textvariable=self.var_view, state='readonly',
                            values=('Resultado', 'Comparar', 'Detección'))
        view.pack(fill='x')
        view.bind('<<ComboboxSelected>>', lambda e: self._on_view_change())

        # Ajustes avanzados (plegados por defecto)
        self._var_advanced = tk.BooleanVar(value=False)
        ttk.Checkbutton(panel, text='Ajustes avanzados', variable=self._var_advanced,
                        command=self._toggle_advanced).pack(anchor='w', pady=(8, 0))
        self._advanced = ttk.Frame(panel)
        self._fill_advanced(self._advanced)

    def _fill_advanced(self, f):
        self.var_thresh = tk.IntVar(value=200)
        ttk.Label(f, text='Umbral de blancura').pack(anchor='w')
        ttk.Scale(f, from_=120, to=255, variable=self.var_thresh,
                  command=lambda v: self.lbl_thresh.config(text=str(int(float(v))))).pack(fill='x', pady=(2, 6))
        self.lbl_thresh = ttk.Label(f, text='200')
        self.lbl_thresh.pack(anchor='w')

        self.var_area = tk.IntVar(value=1500)
        ttk.Label(f, text='Área mínima del globo').pack(anchor='w', pady=(6, 0))
        ttk.Scale(f, from_=100, to=20000, variable=self.var_area,
                  command=lambda v: self.lbl_area.config(text=str(int(float(v))))).pack(fill='x', pady=(2, 6))
        self.lbl_area = ttk.Label(f, text='1500')
        self.lbl_area.pack(anchor='w')

        self.var_radius = tk.IntVar(value=3)
        ttk.Label(f, text='Radio de inpainting').pack(anchor='w', pady=(6, 0))
        ttk.Scale(f, from_=1, to=12, variable=self.var_radius,
                  command=lambda v: self.lbl_radius.config(text=str(int(float(v))))).pack(fill='x', pady=(2, 6))
        self.lbl_radius = ttk.Label(f, text='3')
        self.lbl_radius.pack(anchor='w')

    def _toggle_advanced(self):
        if self._var_advanced.get():
            self._advanced.pack(fill='x', pady=(2, 0))
        else:
            self._advanced.pack_forget()

    def _toggle_panel(self):
        """Plega/muestra el panel lateral para dar más espacio al visor."""
        if self._panel_frame.winfo_ismapped():
            self._panel_frame.pack_forget()
            self.panel_toggle.config(text='▶')
        else:
            self._panel_frame.pack(side='left', fill='y')
            self.panel_toggle.config(text='◀')
        self._refresh_displays()

    def _on_panel_wheel(self, event):
        try:
            if not self._panel_canvas.winfo_ismapped():
                return
            x0 = self._panel_canvas.winfo_rootx()
            y0 = self._panel_canvas.winfo_rooty()
            w = self._panel_canvas.winfo_width()
            h = self._panel_canvas.winfo_height()
            if not (x0 <= event.x_root <= x0 + w and y0 <= event.y_root <= y0 + h):
                return
            self._panel_canvas.yview_scroll(int(-event.delta / 120), 'units')
        except tk.TclError:
            return

    # -------------------------------------------------------- miniaturas
    def _build_thumbs(self):
        self._thumbs_frame = tk.Frame(self.root, bg='#ffffff',
                                      bd=1, relief='solid',
                                      highlightthickness=0,
                                      borderwidth=1)
        bar = tk.Frame(self._thumbs_frame, bg='#ffffff')
        bar.pack(fill='x')
        tk.Label(bar, text='Páginas', bg='#ffffff', fg=COLORS['muted'],
                 font=('Segoe UI', 9, 'bold'), padx=8, pady=3).pack(side='left')
        self._thumb_sbar = ttk.Scrollbar(bar, orient='horizontal')
        self._thumb_sbar.pack(side='bottom', fill='x')
        self._thumb_canvas = tk.Canvas(self._thumbs_frame, bg='#ffffff',
                                       highlightthickness=0, height=94)
        self._thumb_canvas.configure(xscrollcommand=self._thumb_sbar.set)
        self._thumb_sbar.configure(command=self._thumb_canvas.xview)
        self._thumb_canvas.pack(fill='x')
        self._thumbs_frame.pack(side='bottom', fill='x', padx=8, pady=(0, 2))
        self._thumbs_frame.pack_forget()  # solo visible cuando hay páginas

    def _load_thumbnails(self):
        self._thumb_canvas.delete('all')
        self._thumbs = []
        self._thumb_items = {}
        self._thumb_hl = None
        n = len(self.image_list)
        if n == 0:
            self._thumbs_frame.pack_forget()
            return
        self._thumbs_frame.pack(side='bottom', fill='x', padx=8, pady=(0, 2))

        def worker():
            for i, p in enumerate(self.image_list[:300]):
                try:
                    with Image.open(p) as im:
                        im.thumbnail((52, 76))
                        rgb = im.convert('RGB').copy()
                        self._post(lambda idx=i, img=rgb: self._add_thumb(idx, img, n))
                except Exception:
                    pass

        threading.Thread(target=worker, daemon=True).start()

    def _add_thumb(self, idx, img, total):
        x = idx * 64
        photo = ImageTk.PhotoImage(img)
        self._thumbs.append((idx, photo))
        try:
            tag = f't{idx}'
            self._thumb_canvas.create_rectangle(x + 2, 4, x + 62, 82,
                                                fill='#f4f6f8',
                                                outline=COLORS['line'],
                                                tags=tag)
            self._thumb_canvas.create_image(x + 32, 44, image=photo, tags=tag)
            self._thumb_canvas.create_text(x + 32, 90, text=str(idx + 1),
                                           font=('Segoe UI', 9, 'bold'),
                                           fill=COLORS['muted'], tags=tag)
            self._thumb_canvas.tag_bind(tag, '<Button-1>',
                                        lambda e, i=idx: self._goto_thumb(i))
        except tk.TclError:
            return  # ventana cerrada mientras se cargaba
        self._thumb_canvas.configure(scrollregion=(0, 0, total * 64, 96))
        if idx == self.index:
            self._highlight_thumb(idx)

    def _highlight_thumb(self, idx):
        if self._thumb_canvas is None or self._thumb_canvas.winfo_exists() == 0:
            return
        if self._thumb_hl is not None:
            self._thumb_canvas.delete(self._thumb_hl)
        x = idx * 64
        self._thumb_hl = self._thumb_canvas.create_rectangle(
            x, 1, x + 63, 95, outline=COLORS['teal'], width=3)
        self._thumb_canvas.tag_raise(self._thumb_hl)

    def _ensure_thumb_visible(self):
        if not self._thumb_canvas.winfo_exists() or self._thumb_canvas.winfo_width() < 10:
            return
        x = self.index * 64
        x1 = self._thumb_canvas.canvasx(0)
        vis = self._thumb_canvas.winfo_width()
        if not (x1 <= x <= x1 + vis - 70):
            self._thumb_canvas.xview_moveto(max(0.0, (x - 20) / max(1.0, (len(self.image_list) * 64))))

    def _goto_thumb(self, idx):
        if self._busy:
            self.set_status('Esperá: procesando la página actual...')
            return
        self.index = idx
        self._load_current()

    def _on_view_change(self):
        mode = self.var_view.get()
        if mode == 'Comparar':
            self.right_caption.config(text='COMPARAR · arrastrá el borde')
            self._set_tool('none')
            self._enable_manual_tools(False)
        else:
            self.right_caption.config(text='DETECCIÓN' if mode == 'Detección'
                                      else 'RESULTADO')
            self._enable_manual_tools(True)
        self._refresh_displays()

    def _enable_manual_tools(self, enabled):
        state = 'normal' if enabled else 'disabled'
        for b in self._tool_buttons.values():
            b.config(state=state)

    # ----------------------------------------------------------- comparar
    def _compare_composite(self, pos):
        """Mitad original, mitad resultado, con un borde para arrastrar."""
        orig = self.original
        res = self.result if self.result is not None else self.original
        h, w = orig.shape[:2]
        x = max(8, min(w - 8, int(pos * w)))
        combined = np.hstack([orig[:, :x], res[:, x:]])
        cv2.line(combined, (x, 0), (x, h), (255, 255, 255), 3)
        return combined

    def _compare_fraction_from_x(self, event_x):
        sc = self.result_canvas
        if self.original is None or sc._np_image is None or sc._item is None \
                or sc._render_scale <= 0:
            return
        ix, _ = sc.canvas.coords(sc._item)
        w = sc._np_image.shape[1]
        px = (sc.canvas.canvasx(event_x) - ix) / sc._render_scale
        self._compare_pos = max(0.02, min(0.98, px / w))

    def _build_viewer(self, parent):
        images = ttk.PanedWindow(parent, orient='horizontal')
        images.pack(side='left', fill='both', expand=True, padx=(8, 0))
        self.viewer = images
        C = COLORS
        left = ttk.Frame(images)
        self.original_canvas = ZoomableCanvas(left)
        self.original_canvas.pack(fill='both', expand=True, padx=2, pady=(2, 2))
        tk.Label(left, text='ORIGINAL', bg=C['navy'], fg='white',
                 font=('Segoe UI', 9, 'bold')).pack(fill='x', ipady=2)
        images.add(left, weight=1)
        right = ttk.Frame(images)
        self.result_canvas = ZoomableCanvas(right)
        self.result_canvas.pack(fill='both', expand=True, padx=2, pady=(2, 2))
        self.right_caption = tk.Label(right, text='RESULTADO', bg=C['teal'], fg='white',
                                      font=('Segoe UI', 9, 'bold'))
        self.right_caption.pack(fill='x', ipady=2)
        images.add(right, weight=1)

        cv = self.result_canvas.canvas
        cv.bind('<ButtonPress-1>', self._on_canvas_press)
        cv.bind('<B1-Motion>', self._on_canvas_drag)
        cv.bind('<ButtonRelease-1>', self._on_canvas_release)
        cv.bind('<Motion>', self._on_canvas_motion)
        cv.bind('<Leave>', lambda e: self._hide_hover())
        cv.bind('<Escape>', lambda e: self._cancel_drawing())

    def _build_ocr_panel(self):
        tf = ttk.LabelFrame(self.root, text='Texto extraído de los globos', padding=6)
        tf.pack(side='bottom', fill='x', padx=8, pady=(0, 2))
        trow = ttk.Frame(tf)
        trow.pack(fill='x', pady=(0, 2))
        ttk.Button(trow, text='Copiar texto', command=self.copy_ocr_text).pack(side='left')
        ttk.Button(trow, text='Guardar texto...', command=self.save_ocr_text).pack(side='left', padx=(6, 0))
        self.ocr_toggle = ttk.Button(trow, text='▲', width=2,
                                     command=self._toggle_ocr_panel)
        self.ocr_toggle.pack(side='right')
        self.ocr_hint = ttk.Label(trow, text='', foreground=COLORS['muted'])
        self.ocr_hint.pack(side='right', padx=(0, 6))
        self.ocr_text = ScrolledText(tf, height=4, wrap='word', font=('Segoe UI', 10))
        self.ocr_text.pack(fill='x')
        self.ocr_text.insert('1.0', 'Al procesar una página se mostrará aquí el texto '
                                   'detectado en cada globo, antes de limpiarlo.')
        self._update_ocr_hint()

    def _toggle_ocr_panel(self):
        if self.ocr_text.winfo_ismapped():
            self.ocr_text.pack_forget()
            self.ocr_toggle.config(text='▼')
        else:
            self.ocr_text.pack(fill='x')
            self.ocr_toggle.config(text='▲')

    def _toggle_viewer(self):
        if getattr(self, 'viewer', None) is None:
            return
        if self.viewer.winfo_ismapped():
            self.viewer.pack_forget()
            self.view_btn.config(text='Mostrar imagen')
            self.set_status('Visor oculto. Tocá "Mostrar imagen" para ver la página.')
            self._toast('Visor oculto', 'info')
        else:
            self.viewer.pack(side='left', fill='both', expand=True, padx=(8, 0))
            self.view_btn.config(text='Ocultar imagen')
            self.set_status('Visor visible.')
            self._toast('Visor visible', 'info')

    def _build_status_bar(self):
        ttk.Separator(self.root, orient='horizontal').pack(side='bottom', fill='x')
        sbar = tk.Frame(self.root, bg='#ffffff')
        sbar.pack(side='bottom', fill='x')
        self.status = tk.Label(sbar, text='Preparado.', anchor='w',
                               fg=COLORS['muted'], bg='#ffffff',
                               font=('Segoe UI', 10), padx=12, pady=6)
        self.status.pack(side='left', fill='x', expand=True)
        self._progress = ttk.Progressbar(sbar, mode='indeterminate', length=120)

    def _placeholder_image(self):
        w, h = 1080, 680
        top, bottom = (10, 58, 68), (14, 112, 104)
        pil = _gradient_pil(w, h, top, bottom)
        from PIL import ImageDraw, ImageFont
        d = ImageDraw.Draw(pil)
        try:
            lg = Image.open(_assets_dir() / 'logo.png').resize((200, 200), Image.LANCZOS)
            pil.paste(lg, (w // 2 - 100, 50), lg)
        except Exception:
            pass

        def _font(size):
            try:
                return ImageFont.load_default(size=size)
            except TypeError:
                return ImageFont.load_default()

        d.rounded_rectangle([w // 2 - 220, 290, w // 2 + 220, 390], radius=24,
                            fill=(255, 255, 255, 36), outline=(255, 255, 255, 90), width=2)
        d.text((w // 2, 316), 'Manga Bubble Cleaner', font=_font(36), fill='#ffffff', anchor='mm')
        d.text((w // 2, 362), 'Tu asistente para limpiar y traducir tus manhwas',
               font=_font(24), fill='#d8f3f4', anchor='mm')
        d.text((w // 2, 425), '1  Abrí tu página   ·   2  Procesá   ·   3  Copiá o guardá',
               font=_font(20), fill='#b9e0e2', anchor='mm')
        d.text((w // 2, 480), 'Atajos  |  Ctrl+O abrir   ·   Ctrl+Shift+O carpeta   ·   Ctrl+P procesar',
               font=_font(17), fill='#9fc9cd', anchor='mm')
        return cv2.cvtColor(np.array(pil), cv2.COLOR_RGB2BGR)

    def _bind_shortcuts(self):
        r = self.root
        r.bind('<Control-o>', self._shortcut_open)
        r.bind('<Control-O>', self._shortcut_open)
        r.bind('<Control-Shift-Key-O>', self._shortcut_open_folder)
        r.bind('<Control-p>', self._shortcut_process)
        r.bind('<Control-P>', self._shortcut_process)
        r.bind('<Control-s>', self._shortcut_save)
        r.bind('<Control-S>', self._shortcut_save)
        r.bind('<Control-plus>', lambda e: (self.zoom_in(), 'break')[1])
        r.bind('<Control-minus>', lambda e: (self.zoom_out(), 'break')[1])
        r.bind('<Control-0>', lambda e: (self.zoom_fit(), 'break')[1])
        r.bind('<Control-Right>', lambda e: (self.next_image(), 'break')[1])
        r.bind('<Control-Left>', lambda e: (self.prev_image(), 'break')[1])

    def _shortcut_open(self, event):
        self.open_image()
        return 'break'

    def _shortcut_open_folder(self, event):
        self.open_folder()
        return 'break'

    def _shortcut_process(self, event):
        if not self._busy and self.original is not None:
            self.process_current()
        return 'break'

    def _shortcut_save(self, event):
        if self.result is not None:
            self.save_image()
        return 'break'

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
        self._load_thumbnails()
        self._load_current()
        self._toast('Página abierta', 'ok')

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
        self._load_thumbnails()
        self._load_current()
        self._toast(f'Carpeta abierta: {len(files)} páginas', 'ok')

    def prev_image(self):
        if self.image_list and not self._busy:
            self.index = (self.index - 1) % len(self.image_list)
            self._load_current()

    def next_image(self):
        if self.image_list and not self._busy:
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
        self.ocr_results = None
        self._undo_stack = []
        self._auto_result = None
        self._cancel_drawing()
        self._update_undo_state()
        self._show_ocr_results(None)
        self._fit = True
        self._refresh_displays()
        self._update_nav_state()
        self.set_status(f'Cargada: {path.name}  ({self.original.shape[1]}x{self.original.shape[0]})')
        if self.var_auto.get():
            self.process_current()

    def _update_nav_state(self):
        if self.image_list:
            self.nav_label.config(text=f'Página {self.index + 1} de {len(self.image_list)}')
            self._highlight_thumb(self.index)
            self._ensure_thumb_visible()
        else:
            self.nav_label.config(text='Sin página cargada')

    def _right_image(self):
        if self.var_view.get() == 'Detección' and self.detection_overlay is not None:
            return self.detection_overlay
        return self.result

    def _right_image_for_display(self):
        if self.var_view.get() == 'Comparar' and self.original is not None:
            return self._compare_composite(self._compare_pos)
        return self._right_image()

    def _refresh_displays(self):
        if self.original is None:
            ph = self._placeholder_image()
            self.original_canvas.set_image(ph)
            self.result_canvas.set_image(ph)
            return
        right = self._right_image_for_display()
        if self._fit:
            self.original_canvas.set_image(self.original)
            self.result_canvas.set_image(right)
        else:
            self.original_canvas.set_image(self.original, scale=self._scale)
            self.result_canvas.set_image(right, scale=self._scale)

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
            'extract_text': self.var_ocr.get(),
            'ocr_lang': self.var_ocr_lang.get(),
        }

    # ------------------------------------------------------------- OCR
    def _update_ocr_hint(self):
        lang = self.var_ocr_lang.get()
        hint = f'Motor OCR: {"disponible" if self._ocr.is_available() else "NO instalado"}'
        if not self._ocr.is_available():
            hint += '  (pip install rapidocr-onnxruntime)'
        rec = self._ocr._rec_model_path(lang)
        if lang in self._ocr.REC_MODELS and not rec:
            hint += f'  · Modelo {lang} no encontrado en models/ (se usará el estándar)'
        self.ocr_hint.config(text=hint)

    def _show_ocr_results(self, results, msg=None):
        self.ocr_text.delete('1.0', 'end')
        if msg:
            self.ocr_text.insert('1.0', msg + '\n')
            return
        if not results:
            self.ocr_text.insert('1.0', 'No se detectó texto en los globos.')
            return
        self.ocr_text.insert('1.0', ocr_transcript(results))

    def copy_ocr_text(self):
        text = self.ocr_text.get('1.0', 'end-1c').strip()
        if not text:
            self.set_status('No hay texto extraído para copiar.')
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self.set_status('Texto extraído copiado al portapapeles.')
        self._toast('Texto copiado al portapapeles', 'ok')

    def save_ocr_text(self):
        text = self.ocr_text.get('1.0', 'end-1c').strip()
        if not text:
            messagebox.showinfo('Aviso', 'No hay texto extraído para guardar.')
            return
        default = self.current_path.stem + '_texto.txt' if self.current_path else 'texto_extraido.txt'
        path = filedialog.asksaveasfilename(
            title='Guardar texto extraído',
            defaultextension='.txt',
            initialfile=default,
            filetypes=[('Texto', '*.txt')])
        if not path:
            return
        with open(path, 'w', encoding='utf-8') as fh:
            fh.write(text)
        self.set_status(f'Texto guardado: {path}')
        self._toast('Texto guardado', 'ok')

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
                bubbles, result, ocr_out, ocr_msg = self._detect_and_clean(image, params)
                debug = self._build_detection_view(image, bubbles)
                self._post(lambda: self._on_processed(bubbles, result, debug, ocr_out, ocr_msg))
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

        ocr_out = None
        ocr_msg = None
        if params.get('extract_text'):
            if not self._ocr.is_available():
                ocr_msg = ('OCR no disponible: falta el paquete rapidocr-onnxruntime.\n'
                           'Instalalo con: uv pip install rapidocr-onnxruntime')
            else:
                try:
                    ocr_out = self._ocr.extract_bubbles(
                        image, detections, lang=params.get('ocr_lang', 'auto'))
                    if ocr_out is None:
                        ocr_msg = self._ocr.load_error or 'No se pudo usar el OCR.'
                except Exception as exc:
                    ocr_msg = f'Error leyendo el texto de los globos: {exc}'

        result = image.copy()
        for (x1, y1, x2, y2), m in zip(bubbles, masks):
            result = self.cleaner.inpaint_bubble(
                result, x1, y1, x2, y2, radius=params['radius'], bubble_mask=m)
        if params.get('clean_free_text'):
            rows = self.cleaner.find_text_rows(result)
            result = self.cleaner.inpaint_free_text(
                result, rows, radius=params['radius'])
        return bubbles, result, ocr_out, ocr_msg

    @staticmethod
    def _build_detection_view(image, bubbles):
        debug = image.copy()
        for i, (x1, y1, x2, y2) in enumerate(bubbles, 1):
            cv2.rectangle(debug, (x1, y1), (x2, y2), (0, 255, 0), 3)
            cv2.putText(debug, str(i), (x1 + 8, y1 + 30),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 255, 0), 2, cv2.LINE_AA)
        return debug

    def _on_processed(self, bubbles, result, debug, ocr_out=None, ocr_msg=None):
        self._set_busy(False)
        self.result = result
        self._auto_result = result.copy()
        self._undo_stack.clear()
        self.ocr_results = ocr_out
        self.detection_overlay = debug
        self.var_view.set('Resultado')
        self._refresh_displays()
        self._update_undo_state()
        self._show_ocr_results(ocr_out, ocr_msg)
        n_text = sum(1 for r in (ocr_out or []) if r.get('text'))
        extra = f' | {n_text} globos con texto extraído' if n_text else ''
        self.set_status(f'Listo: {len(bubbles)} globos detectados y limpiados.{extra}')
        if bubbles:
            self._celebrate(bubbles)
            self._toast(f'¡Listo! {len(bubbles)} globos limpios.', 'ok')

    def _on_error(self, err):
        self._set_busy(False)
        messagebox.showerror('Error', f'Ocurrió un error:\n{err}')
        self.set_status('Error al procesar.')

    def _set_busy(self, busy):
        self._busy = busy
        self.process_btn.config(state='disabled' if busy else 'normal')
        if busy:
            self.root.config(cursor='watch')
            self._progress.pack(side='right', padx=(8, 10), pady=4)
            self._progress.start(12)
        else:
            self.root.config(cursor='')
            self._progress.stop()
            self._progress.pack_forget()

    # -------------------------------------------------- edición manual
    def _set_tool(self, value):
        self._cancel_drawing()
        self._hide_hover()
        self.var_tool.set(value)
        for key, b in self._tool_buttons.items():
            sel = key == value
            b.config(relief='flat',
                     bg=COLORS['soft'] if sel else '#ffffff',
                     fg=COLORS['teal'] if sel else COLORS['ink'],
                     highlightthickness=3 if sel else 1,
                     highlightbackground=COLORS['teal'] if sel else COLORS['line'],
                     highlightcolor=COLORS['teal'] if sel else COLORS['line'])
        cursor = 'crosshair' if value == 'brush' or value == 'rect' else 'hand2'
        self.result_canvas.canvas.configure(cursor=cursor)
        hints = {
            'none': 'Elegí una herramienta para retocar la página tratada.',
            'brush': 'Pintá encima del texto; al soltar el botón se limpia esa zona.',
            'rect': 'Arrastrá para encerrar un globo o palabra y limpiar su texto.',
        }
        self.help_label.config(text=hints[value])
        self.brush_preview.configure(bg='#ffffff' if value == 'brush'
                                     else COLORS['soft'])
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
        if self.var_view.get() == 'Comparar' and self.original is not None:
            self._compare_dragging = True
            self._last_cmp_x = event.x
            self._compare_fraction_from_x(event.x)
            self._refresh_displays()
            return
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
        if self._compare_dragging:
            if abs(event.x - self._last_cmp_x) < 3:
                return
            self._last_cmp_x = event.x
            self._compare_fraction_from_x(event.x)
            self._refresh_displays()
            return
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
        if self._compare_dragging:
            self._compare_dragging = False
            return
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
        self._toast('Imagen guardada', 'ok')

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
                    _, cleaned, ocr_out, ocr_msg = self._detect_and_clean(page, params)
                    out = out_folder / (p.stem + '_cleaned' + p.suffix.lower())
                    cv2.imwrite(str(out), cleaned)
                    if ocr_out:
                        txt_path = out_folder / (p.stem + '_texto.txt')
                        txt_path.write_text(ocr_transcript(ocr_out), encoding='utf-8')
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
        if 'Errores' not in msg:
            self._toast('Carpeta procesada sin errores', 'ok')


def main():
    root = tk.Tk()
    MangaCleanerApp(root)
    root.mainloop()


if __name__ == '__main__':
    main()