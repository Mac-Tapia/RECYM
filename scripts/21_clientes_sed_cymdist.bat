@echo off
cd /d "%~dp0.."
set PYTHONIOENCODING=utf-8
set PY=.tools\python37-win32\python.exe
if not exist %PY% set PY=python
REM Uso: 21_clientes_sed_cymdist.bat 0326clientesImportantes.xlsb [FEEDER]
REM Si no indica FEEDER, usa active_feeder de config/settings.json
set CI_FILE=%~1
set FEEDER=%~2
if "%FEEDER%"=="" (
  for /f "usebackq delims=" %%A in (`%PY% -c "from core.common import load_json; print(load_json('config/settings.json').get('active_feeder') or '')"`) do set FEEDER=%%A
)
if "%FEEDER%"=="" (
  echo ERROR: indique alimentador o defina active_feeder en config/settings.json
  echo Ejemplo: 21_clientes_sed_cymdist.bat 0326clientesImportantes.xlsb IN112
  exit /b 2
)
if "%CI_FILE%"=="" (
  echo ERROR: indique el archivo de clientesimportantes a usar.
  echo Ejemplo: 21_clientes_sed_cymdist.bat 0326clientesImportantes.xlsb IN112
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
