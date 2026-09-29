@echo off
setlocal
cd /d "%~dp0"
call "scripts\RECYM_Abrir_Estudio.bat"
exit /b %ERRORLEVEL%