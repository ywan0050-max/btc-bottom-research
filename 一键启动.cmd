@echo off
setlocal
cd /d "%~dp0"
title BTC Bottom Research Desk

where powershell.exe >nul 2>&1
if errorlevel 1 (
    echo PowerShell was not found. Windows PowerShell 5.1 or newer is required.
    pause
    exit /b 1
)

powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0start.ps1" -OpenBrowser
set "ExitCode=%ERRORLEVEL%"

if not "%ExitCode%"=="0" (
    echo.
    echo Startup failed. Review the error above, then press any key to close this window.
    pause >nul
)

exit /b %ExitCode%
