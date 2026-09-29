@echo off
setlocal
cd /d "%~dp0.."

set "RECYM_SPA=1"
set "RECYM_ENV=development"
set "RECYM_UI_HOST=127.0.0.1"
set "RECYM_UI_PORT=5055"
set "PY=%CD%\.tools\python37-win32\python.exe"

if not exist "%PY%" (
  echo ERROR: no se encuentra el Python local de RECYM:
  echo %PY%
  pause
  exit /b 1
)

 powershell -NoProfile -ExecutionPolicy Bypass -Command "try { $response = Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:5055/health' -TimeoutSec 2; if ($response.StatusCode -eq 200) { exit 0 } } catch {}; exit 1" >nul 2>&1
if errorlevel 1 start "RECYM API" "%PY%" -u -c "import os,sys; os.environ['RECYM_SPA']='1'; sys.path.insert(0,'src'); from api_app.main import main; main()"

powershell -NoProfile -ExecutionPolicy Bypass -Command "$deadline = (Get-Date).AddSeconds(30); while ((Get-Date) -lt $deadline) { try { $response = Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:5055/health' -TimeoutSec 2; if ($response.StatusCode -eq 200) { Start-Process 'http://127.0.0.1:5055/1'; exit 0 } } catch {}; [System.Threading.Thread]::Sleep(500) }; Write-Error 'La API RECYM no respondio en http://127.0.0.1:5055/health'; exit 1"
if errorlevel 1 (
  echo ERROR: RECYM no pudo iniciar. Revise la ventana "RECYM API" para ver el error.
  pause
  exit /b 1
)

endlocal
exit /b 0
