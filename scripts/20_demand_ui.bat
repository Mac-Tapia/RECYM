@echo off
cd /d "%~dp0.."
set PYTHONIOENCODING=utf-8
set "PY=%CD%\.tools\python37-win32\python.exe"
REM No forzar PA217: usa active_feeder de config/settings.json (estudio aplicado en §1).
REM Para override puntual: set RECYM_FEEDER=IN112
if not defined RECYM_UI_PORT set RECYM_UI_PORT=5055
echo === RECYM UI: demanda + clientes SED + SpotLoad + informe entrega ===
echo Alimentador: (settings.json active_feeder / UI §1)
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
