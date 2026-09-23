@echo off
cd /d "%~dp0.."
set PYTHONIOENCODING=utf-8
set "PY=%CD%\.tools\python37-win32\python.exe"
set RECYM_SPA=1
if not defined RECYM_UI_PORT set RECYM_UI_PORT=5055
if not defined RECYM_UI_HOST set RECYM_UI_HOST=127.0.0.1
if not defined RECYM_ENV set RECYM_ENV=development
if exist ".env" (
  echo [env] cargando .env
)
echo === RECYM UI SPA React + FastAPI §§1-7 ===
echo Puerto: %RECYM_UI_HOST%:%RECYM_UI_PORT%  env=%RECYM_ENV%
echo.

if /I "%RECYM_FORCE_SPA_BUILD%"=="1" goto :build_spa
if not exist "web\dist\index.html" goto :build_spa
goto :after_spa

:build_spa
echo [build] compilando React (web\)...
pushd web
call npm install
if errorlevel 1 (
  echo ERROR npm install
  popd
  pause
  exit /b 1
)
call npm run build
if errorlevel 1 (
  echo ERROR npm run build
  popd
  pause
  exit /b 1
)
popd

:after_spa
if not exist "config\settings.local.json" (
  if exist "config\settings.example.json" (
    echo [config] Tip: cree config\settings.local.json desde settings.example.json para rutas de esta PC.
  )
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
