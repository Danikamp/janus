@echo off
rem Lanza Janus y abre el navegador.
rem Usa el Python portable de python\ para que el USB arranque en cualquier
rem Windows sin instalar nada.
setlocal
cd /d "%~dp0"

set "PY=%~dp0python\python.exe"
if not exist "%PY%" (
  echo.
  echo   Falta el Python portable en "%~dp0python\".
  echo   Descarga el paquete NuGet "python" 3.13 de nuget.org, abre el .nupkg
  echo   como zip y copia su carpeta tools\ aqui con el nombre python\. Despues:
  echo     python\python.exe -m pip install -r requirements.txt
  echo.
  pause
  goto :eof
)

if not exist ".env" (
  copy /y ".env.example" ".env" >nul
  echo.
  echo   Se ha creado .env. Pon tu clave API ahi si quieres usar la IA.
  echo.
)

start "" http://127.0.0.1:8700
"%PY%" -m server.main
