@echo off
REM Script de instalación para Manga Bubble Cleaner
REM Compatible con Windows

echo ============================================
echo    MANGA BUBBLE CLEANER - Instalador
echo ============================================
echo.

REM Verificar si Python está instalado
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo ERROR: Python 3.8+ no está instalado
    echo Por favor instala Python desde: https://python.org
    pause
    exit /b 1
)

REM Verificar si uv está instalado
where uv >nul 2>&1
if %errorlevel% neq 0 (
    echo uv no está instalado, descargando...
    curl -LsSf https://astral.sh/uv/install.sh | sh
    set "PATH=%USERPROFILE%\.local\bin;%PATH%"
)

REM Instalar dependencias
echo.
echo Instalando dependencias con uv...
echo.

cd /d "%~dp0"

if exist "requirements.txt" (
    uv pip install -r requirements.txt
    echo.
    echo Dependencias instaladas correctamente.
) else (
    echo ERROR: No se encontró requirements.txt
    pause
    exit /b 1
)

echo.
echo ============================================
echo    Instalación completada
echo ============================================
echo.
echo Para usar la aplicación:
echo   - Interfaz web:  python web_app.py
echo   - Línea de comandos:  python app.py [ruta_imagen]
echo.
echo Luego abre: http://localhost:5000
echo.
pause