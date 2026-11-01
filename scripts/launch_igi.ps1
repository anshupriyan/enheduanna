# Launch IGI - The Eye of Enheduanna

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Split-Path -Parent $ScriptDir
$WorkspaceRoot = Split-Path -Parent $RepoRoot

$IgiVenv = Join-Path $RepoRoot "igi\.venv\Scripts\python.exe"
$MemvisionVenv = Join-Path $WorkspaceRoot "memvison\.venv\Scripts\python.exe"

if (Test-Path $MemvisionVenv) {
    $PythonExe = $MemvisionVenv
} elseif (Test-Path $IgiVenv) {
    $PythonExe = $IgiVenv
} else {
    $PythonExe = "python"
}

Write-Host "==========================================================" -ForegroundColor DarkYellow
Write-Host "   ::: LAUNCHING IGI (THE EYE OF ENHEDUANNA) :::          " -ForegroundColor Yellow
Write-Host "   Interpreter: $PythonExe" -ForegroundColor Cyan
Write-Host "==========================================================" -ForegroundColor DarkYellow

$IgiDir = Join-Path $RepoRoot "igi"
Set-Location $IgiDir
& $PythonExe main.py
