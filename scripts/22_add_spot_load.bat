@echo off
cd /d "%~dp0.."
set PYTHONIOENCODING=utf-8
set "PY=%CD%\.tools\python37-win32\python.exe"
if "%~1"=="" (
  echo Uso: 22_add_spot_load.bat NODE_ID P_KW [--cosfi 0.95 ^| --q Q_KVAR]
  echo Ejemplo: 22_add_spot_load.bat NODE123 50 --cosfi 0.95
  exit /b 2
)
"%PY%" -u src\pipeline\add_spot_load.py --node %*
pause

