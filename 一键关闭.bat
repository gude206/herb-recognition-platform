@echo off
setlocal
chcp 65001 >nul
set "PSModulePath="
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0platform-launcher.ps1" -Action stop %*
exit /b %errorlevel%
