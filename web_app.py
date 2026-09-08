#!/usr/bin/env python3
"""
Interfaz web para Manga Bubble Cleaner
"""

from flask import Flask, render_template, request, redirect, url_for, send_from_directory
from werkzeug.utils import secure_filename
import os
import cv2
import numpy as np
from pathlib import Path
import uuid

# Importar el limpiador
from app import MangaBubbleCleaner

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['RESULT_FOLDER'] = 'results'
app.config['ALLOWED_EXTENSIONS'] = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max

# Crear carpetas si no existen
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(app.config['RESULT_FOLDER'], exist_ok=True)

cleaner = MangaBubbleCleaner()


def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']


@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        if 'file' not in request.files:
            return render_template('index.html', error='No se seleccionó archivo')
        
        file = request.files['file']
        
        if file.filename == '':
            return render_template('index.html', error='No se seleccionó archivo')
        
        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            unique_id = str(uuid.uuid4())[:8]
            input_filename = f"{unique_id}_{filename}"
            input_path = os.path.join(app.config['UPLOAD_FOLDER'], input_filename)
            
            file.save(input_path)
            
            # Procesar imagen
            output_filename = f"{unique_id}_cleaned_{filename}"
            output_path = os.path.join(app.config['RESULT_FOLDER'], output_filename)
            
            try:
                cleaner.process_image(input_path, output_path, use_yolo=False)
                return render_template('result.html', 
                                      original=input_filename,
                                      cleaned=output_filename,
                                      success=True)
            except Exception as e:
                return render_template('index.html', error=f'Error procesando imagen: {str(e)}')
        
        return render_template('index.html', error='Formato de archivo no permitido')
    
    return render_template('index.html')


@app.route('/uploads/<filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)


@app.route('/results/<filename>')
def result_file(filename):
    return send_from_directory(app.config['RESULT_FOLDER'], filename)


@app.route('/clear')
def clear():
    """Limpiar archivos temporales"""
    import shutil
    for folder in [app.config['UPLOAD_FOLDER'], app.config['RESULT_FOLDER']]:
        for f in os.listdir(folder):
            os.remove(os.path.join(folder, f))
    return redirect(url_for('index'))


if __name__ == '__main__':
    app.run(debug=True, port=5000)