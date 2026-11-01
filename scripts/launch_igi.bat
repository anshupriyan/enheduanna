@echo off
setlocal
set SCRIPT_DIR=%~dp0
set REPO_ROOT=%SCRIPT_DIR%..
set WORKSPACE_ROOT=%REPO_ROOT%\..

if exist "%WORKSPACE_ROOT%\memvison\.venv\Scripts\python.exe" (
    set PYTHON_EXE=%WORKSPACE_ROOT%\memvison\.venv\Scripts\python.exe
) else if exist "%REPO_ROOT%\igi\.venv\Scripts\python.exe" (
    set PYTHON_EXE=%REPO_ROOT%\igi\.venv\Scripts\python.exe
) else (
    set PYTHON_EXE=python
)

echo ==========================================================
echo    ::: LAUNCHING IGI (THE EYE OF ENHEDUANNA) :::
echo    Interpreter: %PYTHON_EXE%
echo ==========================================================

cd /d "%REPO_ROOT%\igi"
"%PYTHON_EXE%" main.py

