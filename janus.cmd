@echo off
rem Lanza Janus y abre el navegador.
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo Primera vez: preparando el entorno...
  python -m venv .venv || goto :error
  .venv\Scripts\python.exe -m pip install -q --disable-pip-version-check -r requirements.txt || goto :error
)

if not exist ".env" (
  copy /y ".env.example" ".env" >nul
  echo.
  echo   Se ha creado .env. Abrelo y pon tu clave API antes de usar Janus.
  echo.
)

start "" http://127.0.0.1:8700
.venv\Scripts\python.exe -m server.main
goto :eof

:error
echo.
echo   Fallo al preparar el entorno. Necesitas Python 3.11 o superior en el PATH.
pause
