@echo off
REM Entrega autonoma del informe RECYM (LF §5 + capturas + Word/Excel/PDF).
REM Uso: scripts\26_deliver_informe.bat [FEEDER]
REM Ejemplo: scripts\26_deliver_informe.bat AL209
setlocal
cd /d "%~dp0.."
set FEEDER=%~1
if "%FEEDER%"=="" set FEEDER=
set PY=.tools\python37-win32\python.exe
if not exist "%PY%" (
  echo ERROR: falta %PY%
  exit /b 1
)
if "%FEEDER%"=="" (
  "%PY%" -m pipeline.deliver_informe --ensure-lf --force-captures
) else (
  "%PY%" -m pipeline.deliver_informe --feeder %FEEDER% --ensure-lf --force-captures
)
exit /b %ERRORLEVEL%
