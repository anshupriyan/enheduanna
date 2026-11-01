# Launch IGI - The Eye of Enheduanna

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Split-Path -Parent $ScriptDir
$WorkspaceRoot = Split-Path -Parent $RepoRoot

$MemvisionVenv1 = Join-Path $RepoRoot "memvison\.venv\Scripts\python.exe"
$MemvisionVenv2 = Join-Path $WorkspaceRoot "memvison\.venv\Scripts\python.exe"
$IgiVenv = Join-Path $RepoRoot "igi\.venv\Scripts\python.exe"

if (Test-Path $MemvisionVenv1) {
    $PythonExe = $MemvisionVenv1
} elseif (Test-Path $MemvisionVenv2) {
    $PythonExe = $MemvisionVenv2
} elseif (Test-Path $IgiVenv) {
    $PythonExe = $IgiVenv
} else {
    $PythonExe = "python"
}

Write-Host "==========================================================" -ForegroundColor DarkYellow
Write-Host "   ::: LAUNCHING IGI (THE EYE OF ENHEDUANNA) :::          " -ForegroundColor Yellow
Write-Host "   Interpreter: $PythonExe" -ForegroundColor Cyan
Write-Host "==========================================================" -ForegroundColor DarkYellow

# JIT Verification: Ensure PySide6 desktop HUD GUI package is installed
$hasIgi = & $PythonExe -c "try: import PySide6; print('ok')`nexcept: print('fail')"
if ($hasIgi -notmatch "ok") {
    Write-Host "`n  [IGI] First-time launch detected: PySide6 GUI package is required." -ForegroundColor Yellow
    Write-Host "  [IGI] Installing PySide6-Essentials for on-screen companion HUD..." -ForegroundColor Cyan

    $igiReq = Join-Path $RepoRoot "igi\requirements.txt"
    $uvCmd = Get-Command uv -ErrorAction SilentlyContinue
    if ($uvCmd) {
        & $uvCmd.Source pip install --python "$PythonExe" -r "$igiReq"
    } else {
        & "$PythonExe" -m pip install -r "$igiReq"
    }
    if ($LASTEXITCODE -ne 0) {
        Write-Host "`n  [FAIL] Failed to install PySide6. Check your internet connection." -ForegroundColor Red
        exit 1
    }
    Write-Host "  [OK] PySide6-Essentials installed successfully.`n" -ForegroundColor Green
}

$IgiDir = Join-Path $RepoRoot "igi"
Set-Location $IgiDir
& $PythonExe main.py
