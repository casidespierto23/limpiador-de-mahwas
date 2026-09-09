@echo off
REM Script para iniciar Manga Bubble Cleaner en modo escritorio (GUI)

cd /d "%~dp0"

REM Usar la version compilada (con logo) si existe
if exist "dist\Manga Bubble Cleaner.exe" (
    start "" "dist\Manga Bubble Cleaner.exe"
    exit /b
)

if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" gui_app.py
) else (
    python gui_app.py
)

echo.
echo La aplicacion se cerro. Presiona una tecla para salir...
pause >nul