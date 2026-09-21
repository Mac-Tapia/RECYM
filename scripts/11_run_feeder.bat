@echo off
cd /d "%~dp0.."
set PYTHONIOENCODING=utf-8
set "PY=%CD%\.tools\python37-win32\python.exe"
echo Uso: 11_run_feeder.bat PA217
echo      11_run_feeder.bat --all-feeders
"%PY%" -u src\pipeline\run_all.py %*
pause

