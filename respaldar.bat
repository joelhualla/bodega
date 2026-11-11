@echo off
title Respaldo de la base de datos
cd /d "%~dp0"

if not exist ".venv\Scripts\activate.bat" (
  echo No encuentro el entorno de Python en esta carpeta.
  pause
  exit /b 1
)

call ".venv\Scripts\activate.bat"
python manage.py respaldar
echo.
pause
