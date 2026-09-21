@echo off
cd /d "%~dp0.."
set PYTHONIOENCODING=utf-8
set "PY=%CD%\.tools\python37-win32\python.exe"
set "PYTHONPATH=%CD%\src;%CD%\src\core"
echo.
echo === DEFAULT → AAAC/XLPE (misma seccion) — sin tocar tensiones de fuentes ===
echo Cierre CYMDIST GUI si tiene la MDB bloqueada.
echo.
"%PY%" -u src\pipeline\fix_default_aaac_xlpe.py %*
set ERR=%ERRORLEVEL%
echo.
pause
exit /b %ERR%
