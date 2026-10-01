@echo off
setlocal
cd /d "%~dp0.."
set PYTHONIOENCODING=utf-8
set "PY=%CD%\.tools\python37-win32\python.exe"
set RECYM_SPA=1
set RECYM_AUTH=1
set RECYM_ISOLATE_JOBS=1

if not exist "%PY%" (
	echo HARNESS FAIL: falta el Python CYME: %PY%
	exit /b 2
)
if not exist "web\node_modules\.bin\vitest.cmd" (
	echo HARNESS FAIL: faltan dependencias web. Ejecute: cd web ^&^& npm ci
	exit /b 2
)
if not exist "web\node_modules\.bin\tsc.cmd" (
	echo HARNESS FAIL: falta TypeScript local. Ejecute: cd web ^&^& npm ci
	exit /b 2
)
"%PY%" -c "import fastapi, httpx" >nul 2>nul
if errorlevel 1 (
	echo HARNESS FAIL: faltan dependencias Python. Ejecute: "%PY%" -m pip install -r requirements.txt
	exit /b 2
)

echo === 1/5 Frontend tests ===
pushd web
call node_modules\.bin\vitest.cmd run
if errorlevel 1 (
	popd
	exit /b 1
)

echo === 2/5 Frontend typecheck ===
call node_modules\.bin\tsc.cmd --noEmit
if errorlevel 1 (
	popd
	exit /b 1
)

echo === 3/5 Production build ===
call npm run build
if errorlevel 1 (
	popd
	exit /b 1
)
popd

echo === 4/5 Python contract and regression tests ===
"%PY%" -m unittest discover -s tests -p "test_*.py"
if errorlevel 1 exit /b 1

echo === 5/5 Runtime readiness smoke ===
"%PY%" -u scripts\smoke_ready_isolation.py
if errorlevel 1 exit /b 1

echo === HARNESS PASS: frontend, Python and readiness ===
exit /b 0
