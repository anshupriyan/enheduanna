@echo off
chcp 65001 > nul
setlocal enabledelayedexpansion

echo ======================================================
echo   Launching Enheduanna 1-Click Environment Setup...
echo ======================================================

powershell -ExecutionPolicy Bypass -NoProfile -File "%~dp0scripts\setup.ps1"

if %ERRORLEVEL% neq 0 (
    echo.
    echo [ERROR] Setup failed with exit code %ERRORLEVEL%.
    pause
    exit /b %ERRORLEVEL%
)

endlocal
