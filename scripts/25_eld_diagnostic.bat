@echo off
cd /d "%~dp0.."
set PYTHONIOENCODING=utf-8
set "PY=%CD%\.tools\python37-win32\python.exe"
set "PYTHONPATH=%CD%\src;%CD%\src\core"
echo.
echo === Herramienta diagnostica CYMDIST (API) → estudio ELD ===
echo Estudio: D:\BaseDatosElectroDunas\260919BaseDatos\proyectos\ELD.zxst
echo.
"%PY%" -u src\analysis\run_eld_diagnostic.py %*
set ERR=%ERRORLEVEL%
echo.
echo Salida: data\output\system\diagnostics\ELD\
pause
exit /b %ERR%
