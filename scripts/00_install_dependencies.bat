@echo off
cd /d "%~dp0.."
set PYTHONIOENCODING=utf-8
set "PY=%CD%\.tools\python37-win32\python.exe"
if not exist "%PY%" (
  echo Falta Python CYME-compatible: %PY%
  exit /b 1
)
"%PY%" -m pip install -r requirements.txt
if exist "web\package.json" (
  echo === npm install web SPA ===
  pushd web
  call npm install
  call npm run build
  popd
)
pause

