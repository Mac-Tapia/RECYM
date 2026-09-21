@echo off
cd /d "%~dp0.."
set PYTHONIOENCODING=utf-8
set "PY=%CD%\.tools\python37-win32\python.exe"
if not defined RECYM_FEEDER set RECYM_FEEDER=PA217
if not defined RECYM_UI_PORT set RECYM_UI_PORT=5055
echo === RECYM UI v4: demanda + clientes SED + SpotLoad + informe entrega ===
echo Alimentador: %RECYM_FEEDER%
echo Puerto: %RECYM_UI_PORT%
echo.
echo Inventario de cargas...
"%PY%" -u src\pipeline\inventory_loads.py
echo.
echo Inventario de nodos/tramos...
"%PY%" -u src\pipeline\inventory_nodes.py
echo.
echo Abriendo http://127.0.0.1:%RECYM_UI_PORT%/
start "" "http://127.0.0.1:%RECYM_UI_PORT%/"
"%PY%" -u src\ui\demand_app.py
pause
