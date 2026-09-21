@echo off
cd /d "%~dp0.."
set PYTHONIOENCODING=utf-8
set "PY=%CD%\.tools\python37-win32\python.exe"
set "PYTHONPATH=%CD%\src;%CD%\src\core"
echo.
echo === Export ASCII CYMDIST (carga TODAS las redes + Update + ExportASCII) ===
echo Cierre CYMDIST GUI si tiene la BD bloqueada, o deje solo la conexion 20260919.
echo.
"%PY%" -u src\pipeline\export_cymdist_ascii.py %*
set ERR=%ERRORLEVEL%
echo.
if %ERR% NEQ 0 (
  echo Nota: si los .txt ya aparecen en exportarTXT, el export fue OK ^(crash tipico CymPy al cerrar^).
)
pause
exit /b %ERR%
