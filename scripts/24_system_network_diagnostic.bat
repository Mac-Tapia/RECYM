@echo off
cd /d "%~dp0.."
set PYTHONIOENCODING=utf-8
set "PY=%CD%\.tools\python37-win32\python.exe"
set "PYTHONPATH=%CD%\src;%CD%\src\core"
echo.
echo === NetworkDiagnostic SISTEMA (todas las redes BD, independiente de §3-4) ===
echo No requiere cabecera ni SpotLoad nueva. Usa equipos/redes de la MDB.
echo.
"%PY%" -u src\analysis\run_system_network_diagnostic.py %*
set ERR=%ERRORLEVEL%
echo.
echo Salida: data\output\system\diagnostics\
pause
exit /b %ERR%
