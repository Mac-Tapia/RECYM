@echo off
cd /d "%~dp0.."
set PYTHONIOENCODING=utf-8
set "PY=%CD%\.tools\python37-win32\python.exe"
set RECYM_SPA=1
if not defined RECYM_UI_PORT set RECYM_UI_PORT=5055
echo === RECYM UI SPA React + FastAPI §§1-7 ===
echo Puerto: %RECYM_UI_PORT%
echo.

if not exist "web\dist\index.html" (
  echo [build] web\dist no encontrado — compilando React...
  pushd web
  call npm install
  call npm run build
  popd
)

echo Inventario de cargas...
"%PY%" -u src\pipeline\inventory_loads.py
echo.
echo Inventario de nodos/tramos...
"%PY%" -u src\pipeline\inventory_nodes.py
echo.
echo Abriendo http://127.0.0.1:%RECYM_UI_PORT%/
start "" "http://127.0.0.1:%RECYM_UI_PORT%/"
"%PY%" -u -c "import os,sys; os.environ['RECYM_SPA']='1'; sys.path.insert(0,'src'); from api_app.main import main; main()"
pause
