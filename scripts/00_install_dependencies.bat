@echo off
cd /d "%~dp0.."
set PYTHONIOENCODING=utf-8
set "PY=%CD%\.tools\python37-win32\python.exe"
if not exist "%PY%" (
  echo Falta Python CYME-compatible: %PY%
  echo Ejecute scripts\00_install_dependencies.bat
  exit /b 1
)
"%PY%" -m pip install -r requirements.txt
pause

