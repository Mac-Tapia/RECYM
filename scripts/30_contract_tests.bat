@echo off
cd /d "%~dp0.."
set PYTHONIOENCODING=utf-8
set "PY=%CD%\.tools\python37-win32\python.exe"
set RECYM_SPA=1
set RECYM_AUTH=1
set RECYM_ISOLATE_JOBS=1
echo === RECYM contract tests + smoke ready ===
"%PY%" -m pip install httpx==0.24.1 -q
"%PY%" -u scripts\smoke_ready_isolation.py
if errorlevel 1 exit /b 1
"%PY%" -u tests\test_api_contract.py
if errorlevel 1 exit /b 1
echo === ALL OK ===
