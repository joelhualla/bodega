@echo off
title Sistema Bodega - NO CERRAR ESTA VENTANA
cd /d "%~dp0"

if not exist ".venv\Scripts\activate.bat" (
  echo No encuentro el entorno de Python en esta carpeta.
  echo Este archivo debe estar junto a manage.py y debes haber creado el entorno con: python -m venv .venv
  pause
  exit /b 1
)

call ".venv\Scripts\activate.bat"

echo Haciendo el respaldo diario de la base de datos...
python manage.py respaldar --diario

echo.
echo Encendiendo el sistema. En unos segundos se abre el navegador.
echo PARA APAGARLO: cierra esta ventana, o presiona Ctrl+C.
start "" cmd /c "timeout /t 4 /nobreak >nul & start http://127.0.0.1:8000/"

python manage.py runserver 127.0.0.1:8000

echo.
echo El sistema se detuvo. Si fue por un error, copia el mensaje de arriba.
pause
