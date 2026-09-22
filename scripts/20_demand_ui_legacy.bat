@echo off
REM Legacy: Flask monolito HTML (sin SPA). Preferir scripts\20_demand_ui.bat
cd /d "%~dp0.."
set PYTHONIOENCODING=utf-8
set "PY=%CD%\.tools\python37-win32\python.exe"
set RECYM_SPA=0
if not defined RECYM_UI_PORT set RECYM_UI_PORT=5055
echo === RECYM UI LEGACY Flask ===
echo Puerto: %RECYM_UI_PORT%
start "" "http://127.0.0.1:%RECYM_UI_PORT%/"
"%PY%" -u src\ui\demand_app.py
pause
