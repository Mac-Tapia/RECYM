@echo off
REM Arranque producción estación (localhost + auth estricta)
cd /d "%~dp0.."
set RECYM_ENV=production
set RECYM_AUTH=1
set RECYM_UI_HOST=127.0.0.1
set RECYM_FORCE_SPA_BUILD=1
set "RECYM_LAUNCHER=%~dp020_demand_ui.bat"
if not exist "%RECYM_LAUNCHER%" (
  echo [RECYM FATAL] Launcher no encontrado: %RECYM_LAUNCHER%
  exit /b 1
)
if /I "%RECYM_LAUNCHER_VALIDATE_ONLY%"=="1" (
  echo LAUNCHER OK: %RECYM_LAUNCHER%
  exit /b 0
)
call "%RECYM_LAUNCHER%"

