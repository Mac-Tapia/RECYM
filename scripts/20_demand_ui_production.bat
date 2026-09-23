@echo off
REM Arranque producción estación (localhost + auth estricta)
cd /d "%~dp0.."
set RECYM_ENV=production
set RECYM_AUTH=1
set RECYM_UI_HOST=127.0.0.1
set RECYM_FORCE_SPA_BUILD=1
call "%~dp0acetamol_ui.bat"
