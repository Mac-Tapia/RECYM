@echo off
cd /d "%~dp0.."
set PYTHONIOENCODING=utf-8
set "PY=%CD%\.tools\python37-win32\python.exe"
"%PY%" -u src\core\test_cymdist_connection.py
pause

