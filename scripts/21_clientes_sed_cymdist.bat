@echo off
cd /d "%~dp0.."
set PYTHONIOENCODING=utf-8
set PY=.tools\python37-win32\python.exe
if not exist %PY% set PY=python
REM Uso: 21_clientes_sed_cymdist.bat 0326clientesImportantes.xlsb [PA217]
set CI_FILE=%~1
set FEEDER=%~2
if "%FEEDER%"=="" set FEEDER=PA217
if "%CI_FILE%"=="" (
  echo ERROR: indique el archivo de clientesimportantes a usar.
  echo Ejemplo: 21_clientes_sed_cymdist.bat 0326clientesImportantes.xlsb PA217
  echo Archivos en data\input\common\clientesimportantes:
  dir /b data\input\common\clientesimportantes\*.xlsb
  exit /b 2
)
echo === Tabla clientes %FEEDER% con %CI_FILE% ===
%PY% -u src\pipeline\build_clientes_table.py --feeder %FEEDER% --clientes-file %CI_FILE%
if errorlevel 1 exit /b 1
echo.
echo === Aplicar EA/Pot a CYMDIST ===
%PY% -u src\pipeline\apply_clientes_to_cymdist.py --feeder %FEEDER% --clientes-file %CI_FILE%
pause
