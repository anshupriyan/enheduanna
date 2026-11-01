@echo off
chcp 65001 > nul
setlocal enabledelayedexpansion

echo ======================================================
echo   Launching Enheduanna 1-Click Environment Setup...
echo ======================================================

set EXTRA_ARGS=%*
if /I "%1"=="fast" set EXTRA_ARGS=-FastMirror
if /I "%1"=="--fast" set EXTRA_ARGS=-FastMirror

powershell -ExecutionPolicy Bypass -NoProfile -File "%~dp0scripts\setup.ps1" !EXTRA_ARGS!

if %ERRORLEVEL% neq 0 (
    echo.
    echo [ERROR] Setup failed with exit code %ERRORLEVEL%.
    pause
    exit /b %ERRORLEVEL%
)

endlocal
