@echo off
cd /d "%~dp0.."
set PYTHONIOENCODING=utf-8
set "PY=%CD%\.tools\python37-win32\python.exe"
if "%~1"=="" (
  echo Uso: 12_new_feeder.bat ID [--name "Nombre"] [--network-id NET_X] [--study-path ruta]
  exit /b 1
)
"%PY%" -u src\core\new_feeder.py %*
pause

