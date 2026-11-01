# Enheduanna End-to-End Environment Setup Script
# Bypasses execution policy and sets up cli-bridge, Python venv, and Core backend.

$ErrorActionPreference = "Stop"

Write-Host "======================================================" -ForegroundColor Cyan
Write-Host "  ENHEDUANNA - Autonomous Desktop AI Framework Setup" -ForegroundColor White
Write-Host "======================================================" -ForegroundColor Cyan

$RepoRoot = (Resolve-Path "$PSScriptRoot\..").Path
$CliBridgePath = (Join-Path $RepoRoot "..\cli-bridge")

Write-Host "Repository Root: $RepoRoot" -ForegroundColor Gray
Write-Host "External CLI Bridge Path: $CliBridgePath" -ForegroundColor Gray
Write-Host ""

# -----------------------------------------------------------------------------
# Prerequisite Checks
# -----------------------------------------------------------------------------
Write-Host "Checking prerequisites..." -ForegroundColor Yellow

# 1. Git
try {
    $gitVer = git --version
    Write-Host "  [OK] Git: $gitVer" -ForegroundColor Green
} catch {
    Write-Host "  [FAIL] Git is not installed or not in PATH. Please install Git." -ForegroundColor Red
    exit 1
}

# 2. Node.js
try {
    $nodeVer = node --version
    Write-Host "  [OK] Node.js: $nodeVer" -ForegroundColor Green
} catch {
    Write-Host "  [FAIL] Node.js is not installed or not in PATH. Please install Node.js v18+." -ForegroundColor Red
    exit 1
}

# 3. Python Resolution
function Find-SystemPython {
    # Check 'python' in PATH (skip WindowsApps 0.0.0.0 stub)
    $pyCmd = Get-Command python -ErrorAction SilentlyContinue
    if ($pyCmd -and $pyCmd.Source -notlike "*WindowsApps*") {
        try {
            $ver = & python --version 2>&1
            if ($ver -match "Python 3\.") { return "python" }
        } catch {}
    }

    # Check 'py' launcher
    $pyLauncher = Get-Command py -ErrorAction SilentlyContinue
    if ($pyLauncher) {
        try {
            $ver = & py -3 --version 2>&1
            if ($ver -match "Python 3\.") { return "py" }
        } catch {}
    }

    # Common Windows install locations (uv, standard Python, Microsoft)
    $searchPatterns = @(
        "$env:LOCALAPPDATA\Programs\Python\Python3*\python.exe",
        "$env:APPDATA\uv\python\cpython-3.1*\python.exe",
        "$env:APPDATA\Roaming\uv\python\cpython-3.1*\python.exe",
        "C:\Python3*\python.exe",
        "C:\Program Files\Python3*\python.exe"
    )
    foreach ($pat in $searchPatterns) {
        $found = Get-ChildItem -Path $pat -ErrorAction SilentlyContinue
        if ($found) {
            return $found[0].FullName
        }
    }

    # Sibling venv fallback
    $siblingVenv = Join-Path $RepoRoot "..\memvison\.venv\Scripts\python.exe"
    if (Test-Path $siblingVenv) {
        return $siblingVenv
    }

    return $null
}

$SystemPython = Find-SystemPython
if (!$SystemPython) {
    Write-Host "  [FAIL] Python 3.10+ was not found on this machine. Please install Python 3.10+." -ForegroundColor Red
    exit 1
}
$pyVer = & $SystemPython --version 2>&1
Write-Host "  [OK] Python: $pyVer ($SystemPython)" -ForegroundColor Green

Write-Host ""

# -----------------------------------------------------------------------------
# Step 1: External Dependency: cli-bridge (branch: meta-hackathon)
# -----------------------------------------------------------------------------
Write-Host "[1/4] Configuring External Dependency: cli-bridge..." -ForegroundColor Cyan

if (!(Test-Path $CliBridgePath)) {
    Write-Host "  Cloning cli-bridge from branch 'meta-hackathon'..." -ForegroundColor Yellow
    git clone -b meta-hackathon https://github.com/anshupriyan/cli-bridge.git "$CliBridgePath"
} else {
    Write-Host "  cli-bridge repository already present at: $CliBridgePath" -ForegroundColor Green
    Write-Host "  Ensuring branch 'meta-hackathon' is checked out..." -ForegroundColor Gray
    git -C "$CliBridgePath" checkout meta-hackathon
}

Write-Host "  Installing and compiling cli-bridge..." -ForegroundColor Gray
Push-Location "$CliBridgePath"
try {
    npm install
    npm run build
    Write-Host "  [OK] cli-bridge built successfully." -ForegroundColor Green
} finally {
    Pop-Location
}

Write-Host ""

# -----------------------------------------------------------------------------
# Step 2: Python Virtual Environment (MemVision + IGI)
# -----------------------------------------------------------------------------
Write-Host "[2/4] Setting up Python Virtual Environment..." -ForegroundColor Cyan

$VenvDir = Join-Path $RepoRoot "memvison\.venv"
$VenvPython = Join-Path $VenvDir "Scripts\python.exe"

if (!(Test-Path $VenvPython)) {
    Write-Host "  Creating virtual environment at $VenvDir..." -ForegroundColor Yellow
    & $SystemPython -m venv "$VenvDir"
} else {
    Write-Host "  Virtual environment found at $VenvDir" -ForegroundColor Green
}

Write-Host "  Installing MemVision and IGI Python dependencies..." -ForegroundColor Gray
& "$VenvPython" -m pip install --quiet --upgrade pip
& "$VenvPython" -m pip install --quiet -r (Join-Path $RepoRoot "memvison\requirements.txt")
& "$VenvPython" -m pip install --quiet -r (Join-Path $RepoRoot "igi\requirements.txt")
Write-Host "  [OK] Python packages installed." -ForegroundColor Green

Write-Host ""

# -----------------------------------------------------------------------------
# Step 3: Enheduanna Core & Dashboard Build
# -----------------------------------------------------------------------------
Write-Host "[3/4] Building Enheduanna Core Orchestrator & Dashboard..." -ForegroundColor Cyan

$CoreDir = Join-Path $RepoRoot "app\core"
Push-Location "$CoreDir"
try {
    npm install
    npm run build
    Write-Host "  [OK] Enheduanna Core built successfully." -ForegroundColor Green
} finally {
    Pop-Location
}

Write-Host ""

# -----------------------------------------------------------------------------
# Step 4: Configuration File Setup
# -----------------------------------------------------------------------------
Write-Host "[4/4] Verifying Configuration..." -ForegroundColor Cyan

$ConfigPath = Join-Path $RepoRoot "enheduanna.config.json"
$ConfigExample = Join-Path $RepoRoot "enheduanna.config.example.json"

if (!(Test-Path $ConfigPath)) {
    if (Test-Path $ConfigExample) {
        Copy-Item "$ConfigExample" "$ConfigPath"
        Write-Host "  [OK] Generated enheduanna.config.json from template." -ForegroundColor Green
    }
} else {
    Write-Host "  [OK] enheduanna.config.json is present." -ForegroundColor Green
}

Write-Host ""
Write-Host "======================================================" -ForegroundColor Green
Write-Host "  🎉 ENHEDUANNA SETUP COMPLETE!" -ForegroundColor Green
Write-Host "======================================================" -ForegroundColor Green
Write-Host ""
Write-Host "Next steps to run:" -ForegroundColor White
Write-Host "  1. Set your Meta API Key (if not already set):" -ForegroundColor Gray
Write-Host "     `$env:META_API_KEY = `"your_api_key_here`"" -ForegroundColor Yellow
Write-Host ""
Write-Host "  2. Start Enheduanna Core Server & Dashboard (Port 4100):" -ForegroundColor Gray
Write-Host "     cd app\core; npm start" -ForegroundColor Yellow
Write-Host "     (Dashboard: http://127.0.0.1:4100)" -ForegroundColor Gray
Write-Host ""
Write-Host "  3. (Optional) Open MemVision Capture Monitoring Dashboard (Port 8765):" -ForegroundColor Gray
Write-Host "     cd memvison; .\venv\Scripts\python.exe main.py ui" -ForegroundColor Yellow
Write-Host ""
Write-Host "  4. (Optional) Launch IGI Visual Companion HUD:" -ForegroundColor Gray
Write-Host "     .\scripts\launch_igi.bat" -ForegroundColor Yellow
Write-Host ""
