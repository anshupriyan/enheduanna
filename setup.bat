@echo off
chcp 65001 > nul
setlocal

echo ======================================================
echo   Launching Enheduanna 1-Click Environment Setup...
echo   fresh clone = full install, re-run = ~2s skip
echo ======================================================

powershell -ExecutionPolicy Bypass -NoProfile -File "%~dp0scripts\setup.ps1" %*

if %ERRORLEVEL% equ 0 goto :success

echo.
echo [ERROR] Setup failed with exit code %ERRORLEVEL%.
echo Re-run setup.bat to retry - it resumes where it left off.
pause
exit /b %ERRORLEVEL%

:success
echo.
echo Setup complete. Run: cd app\core ^& npm start  -  Dashboard: http://127.0.0.1:4100
pause
endlocal
