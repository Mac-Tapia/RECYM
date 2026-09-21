@echo off
cd /d "%~dp0.."
set PYTHONIOENCODING=utf-8
set "PY=%CD%\.tools\python37-win32\python.exe"
REM No forzar PA217: respeta active_feeder del settings / estudio §1.
if not defined RECYM_UI_PORT set RECYM_UI_PORT=5055
if not defined RECYM_UI_THREADS set RECYM_UI_THREADS=24

echo === RECYM: restablecer UI (libera puerto y reinicia) ===
echo Puerto: %RECYM_UI_PORT%  · threads: %RECYM_UI_THREADS%

REM Matar TODOS los listeners del puerto (puede haber varios CloseWait/zombie)
for /L %%i in (1,1,5) do (
  for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":%RECYM_UI_PORT% " ^| findstr LISTENING') do (
    echo Matando PID %%a en puerto %RECYM_UI_PORT% ...
    taskkill /F /PID %%a >nul 2>&1
  )
  timeout /t 1 /nobreak >nul
)

echo Abriendo http://127.0.0.1:%RECYM_UI_PORT%/
start "" "http://127.0.0.1:%RECYM_UI_PORT%/"
"%PY%" -u src\ui\demand_app.py
pause
