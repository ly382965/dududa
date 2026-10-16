@echo off
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0start.ps1" %*
set "dududa_exit=%ERRORLEVEL%"
if "%~1"=="" pause
exit /b %dududa_exit%
