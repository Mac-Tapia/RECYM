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

powershell -NoProfile -ExecutionPolicy Bypass -Command "$up = Test-NetConnection -ComputerName 127.0.0.1 -Port 5055 -InformationLevel Quiet; if (-not $up) { Start-Process -FilePath '%PY%' -WorkingDirectory '%CD%' -ArgumentList @('-u','-c','import os,sys; os.environ[''RECYM_SPA'']=''1''; sys.path.insert(0,''src''); from api_app.main import main; main()') }; Start-Process 'http://127.0.0.1:5055/1'"

endlocal
exit /b 0
