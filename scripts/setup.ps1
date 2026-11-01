# Enheduanna 1-Click Environment Setup Script
# Fresh clone -> double-click setup.bat -> everything ready.
# Features: instant ~2s idempotent re-runs, parallel node builds, auto-uv acceleration, zero pipe deadlocks.

param(
    [switch]$WithIgi, # Force install PySide6 desktop HUD upfront (skip prompt)
    [switch]$NoIgi,   # Force skip PySide6 desktop HUD (skip prompt)
    [switch]$Force    # Force reinstall/rebuild even if already built
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

Write-Host "======================================================" -ForegroundColor Cyan
Write-Host "  ENHEDUANNA - 1-Click Setup Engine" -ForegroundColor White
Write-Host "======================================================" -ForegroundColor Cyan

$RepoRoot = (Resolve-Path "$PSScriptRoot\..").Path
$CoreDir = Join-Path $RepoRoot "app\core"
$VenvDir = Join-Path $RepoRoot "memvison\.venv"
$VenvPython = Join-Path $VenvDir "Scripts\python.exe"
$MemReq = Join-Path $RepoRoot "memvison\requirements.txt"
$IgiReq = Join-Path $RepoRoot "igi\requirements.txt"

# Resolve cli-bridge location (supports both sibling and self-contained repo layouts)
$CliBridgeSibling = (Resolve-Path (Join-Path $RepoRoot "..\cli-bridge") -ErrorAction SilentlyContinue)
$CliBridgeLocal = Join-Path $RepoRoot "cli-bridge"

$CliBridgePath = if ($CliBridgeSibling) { $CliBridgeSibling.Path } elseif (Test-Path $CliBridgeLocal) { $CliBridgeLocal } else { Join-Path $RepoRoot "..\cli-bridge" }

Write-Host "  Repository Root: $RepoRoot" -ForegroundColor Gray
Write-Host "  CLI Bridge Path: $CliBridgePath" -ForegroundColor Gray
Write-Host ""

# -----------------------------------------------------------------------------
# Zero-Deadlock Visual Spinner Execution Engine
# Uses temporary files to eliminate OS pipe buffer deadlocks across all Windows versions
# -----------------------------------------------------------------------------
function Invoke-FastStep {
    param(
        [string]$Tag,
        [string]$Title,
        [string]$FileName,
        [string]$Arguments = "",
        [string]$WorkingDirectory = $RepoRoot
    )

    $frames = @('|', '/', '-', '\')
    if ([Console]::OutputEncoding.CodePage -eq 65001) {
        $frames = @('⠋', '⠙', '⠹', '⠸', '⠼', '⠴', '⠦', '⠧', '⠇', '⠏')
    }
    $sw = [System.Diagnostics.Stopwatch]::StartNew()

    $outFile = [System.IO.Path]::GetTempFileName()
    $errFile = [System.IO.Path]::GetTempFileName()

    $pinfo = New-Object System.Diagnostics.ProcessStartInfo
    $pinfo.FileName = "cmd.exe"
    $pinfo.Arguments = "/c `"$FileName $Arguments > `"$outFile`" 2> `"$errFile`"`""
    $pinfo.WorkingDirectory = $WorkingDirectory
    $pinfo.UseShellExecute = $false
    $pinfo.CreateNoWindow = $true

    $proc = [System.Diagnostics.Process]::Start($pinfo)
    $i = 0

    while (!$proc.HasExited) {
        $elapsed = [math]::Round($sw.Elapsed.TotalSeconds)
        $spinner = $frames[$i % $frames.Length]
        Write-Host -NoNewline "`r  $spinner $Tag $Title ($($elapsed)s)...       " -ForegroundColor Yellow
        Start-Sleep -Milliseconds 100
        $i++
    }

    $proc.WaitForExit()
    $stdout = Get-Content $outFile -Raw -ErrorAction SilentlyContinue
    $stderr = Get-Content $errFile -Raw -ErrorAction SilentlyContinue
    Remove-Item $outFile, $errFile -Force -ErrorAction SilentlyContinue
    $totalSec = [math]::Round($sw.Elapsed.TotalSeconds, 1)

    if ($proc.ExitCode -eq 0) {
        Write-Host "`r  [OK] $Tag $Title (done in $($totalSec)s)                        " -ForegroundColor Green
        return $stdout
    } else {
        Write-Host "`r  [FAIL] $Tag $Title (failed after $($totalSec)s)                     " -ForegroundColor Red
        if ($stderr) {
            Write-Host "    $stderr" -ForegroundColor DarkRed
        } elseif ($stdout) {
            Write-Host "    $stdout" -ForegroundColor DarkRed
        }
        throw "Step $Tag failed with exit code $($proc.ExitCode)"
    }
}

function Test-NodeIsBuilt($Dir) {
    $modules = Join-Path $Dir "node_modules"
    $dist = Join-Path $Dir "dist"
    $build = Join-Path $Dir "build"
    $target = if (Test-Path $dist) { $dist } elseif (Test-Path $build) { $build } else { $null }
    return ((Test-Path $modules) -and ($target -ne $null))
}

# -----------------------------------------------------------------------------
# Prerequisite Verification
# -----------------------------------------------------------------------------
Write-Host "Checking prerequisites..." -ForegroundColor Gray

# Git Check
try {
    $gitVer = (git --version).Trim()
    Write-Host "  [OK] Git: $gitVer" -ForegroundColor Green
} catch {
    Write-Host "  [FAIL] Git is not installed or not in PATH. Please install Git." -ForegroundColor Red
    exit 1
}

# Node.js Check
try {
    $nodeVer = (node --version).Trim()
    Write-Host "  [OK] Node.js: $nodeVer" -ForegroundColor Green
} catch {
    Write-Host "  [FAIL] Node.js is not installed or not in PATH. Please install Node.js v18+." -ForegroundColor Red
    exit 1
}

# High-Speed uv Engine Auto-Resolution / Auto-Installation
$uvExe = $null
$uvCmd = Get-Command uv -ErrorAction SilentlyContinue
if ($uvCmd) {
    $uvExe = $uvCmd.Source
} elseif (Test-Path "$env:USERPROFILE\.local\bin\uv.exe") {
    $uvExe = "$env:USERPROFILE\.local\bin\uv.exe"
}

if (!$uvExe) {
    Write-Host "  [INFO] uv not detected. Attempting quick auto-install (pip install uv)..." -ForegroundColor Cyan
    try {
        pip install --quiet uv 2>$null
        $uvCmd = Get-Command uv -ErrorAction SilentlyContinue
        if ($uvCmd) { $uvExe = $uvCmd.Source }
    } catch {}
}

if ($uvExe) {
    Write-Host "  [OK] High-Speed Engine: uv detected ($uvExe)" -ForegroundColor Green
} else {
    Write-Host "  [INFO] uv not detected. Running standard pip (tip: 'pip install uv' makes installs 10x faster)." -ForegroundColor DarkYellow
}

# Python Engine Resolution (Strict >= 3.10, prefer 3.12/3.11)
$pyExe = $null
if ($uvExe) {
    try {
        $c = (& $uvExe python find 3.12 2>$null).Trim()
        if (!$c) { $c = (& $uvExe python find 3.11 2>$null).Trim() }
        if (!$c) { $c = (& $uvExe python find 3.10 2>$null).Trim() }
        if ($c -and (Test-Path $c)) { $pyExe = $c }
    } catch {}
}

if (!$pyExe) {
    $candidates = @(
        "python",
        "py",
        "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python311\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python310\python.exe",
        "C:\Python312\python.exe",
        "C:\Python311\python.exe",
        "C:\Python310\python.exe"
    )

    foreach ($cand in $candidates) {
        try {
            $p = (Get-Command $cand -ErrorAction SilentlyContinue).Source
            if (!$p) { $p = $cand }
            if (Test-Path $p) {
                $t = & "$p" -c 'import sys; print(1 if sys.version_info >= (3, 10) else 0)' 2>$null
                if ($t -match "1") {
                    $pyExe = $p
                    break
                }
            }
        } catch {}
    }
}

if (!$pyExe -and $uvExe) {
    Write-Host "  [INFO] Installing Python 3.12 via uv..." -ForegroundColor Cyan
    & $uvExe python install 3.12
    $pyExe = (& $uvExe python find 3.12 2>$null).Trim()
}

if (!$pyExe) {
    Write-Host "  [FAIL] Python 3.10+ not found in PATH or standard install locations." -ForegroundColor Red
    Write-Host "         Please install Python from https://www.python.org/downloads/ (check 'Add to PATH')." -ForegroundColor Yellow
    exit 1
}

$pyVersion = (& $pyExe --version 2>&1).Trim()
Write-Host "  [OK] Python: $pyVersion" -ForegroundColor Green
Write-Host ""

# -----------------------------------------------------------------------------
# Step 1: External CLI Bridge Setup (branch-locked: meta-hackathon)
# -----------------------------------------------------------------------------
if (!(Test-Path $CliBridgePath)) {
    Invoke-FastStep -Tag "[1/4]" -Title "Cloning cli-bridge (branch: meta-hackathon)" -FileName "git" -Arguments "clone -b meta-hackathon https://github.com/anshupriyan/cli-bridge.git `"$CliBridgePath`""
} else {
    Invoke-FastStep -Tag "[1/4]" -Title "Verifying cli-bridge branch (meta-hackathon)" -FileName "git" -Arguments "checkout meta-hackathon" -WorkingDirectory $CliBridgePath
    try {
        Invoke-FastStep -Tag "[1/4]" -Title "Pulling latest cli-bridge updates" -FileName "git" -Arguments "pull origin meta-hackathon" -WorkingDirectory $CliBridgePath
    } catch {
        Write-Host "  [WARN] [1/4] Could not pull cli-bridge updates (offline or network unreachable). Using local copy." -ForegroundColor Yellow
    }
}

# -----------------------------------------------------------------------------
# Step 2: High-Speed Python Virtual Environment (MemVision + IGI)
# -----------------------------------------------------------------------------
if (!(Test-Path $VenvPython) -or $Force) {
    if ($uvExe) {
        Invoke-FastStep -Tag "[2/4]" -Title "Creating virtual environment with uv (instant)" -FileName $uvExe -Arguments "venv `"$VenvDir`" --python `"$pyExe`""
    } else {
        Invoke-FastStep -Tag "[2/4]" -Title "Creating virtual environment (python -m venv)" -FileName $pyExe -Arguments "-m venv `"$VenvDir`""
    }
} else {
    Write-Host "  [OK] [2/4] Virtual environment exists at memvison\.venv" -ForegroundColor Green
}

# -----------------------------------------------------------------------------
# Part A: Core Dependencies (MemVision Scribe & OCR - 23 MB)
# -----------------------------------------------------------------------------
$needsCorePy = $Force
if (!$needsCorePy) {
    $probe = & "$VenvPython" -c "try: import mss, PIL, numpy, httpx; print('ok')`nexcept: print('fail')"
    if ($probe -notmatch "ok") { $needsCorePy = $true }
}

if (!$needsCorePy) {
    Write-Host "  [OK] [2/4] Core Python dependencies (MemVision) already installed." -ForegroundColor Green
} else {
    Write-Host "  [2/4] Installing core Python packages (MemVision Scribe)..." -ForegroundColor Cyan
    $swInstall = [System.Diagnostics.Stopwatch]::StartNew()
    $env:UV_HTTP_TIMEOUT = "120"
    $env:UV_CONCURRENT_DOWNLOADS = "50"

    if ($uvExe) {
        & $uvExe pip install --python "$VenvPython" -r "$MemReq"
    } else {
        & "$VenvPython" -m pip install --prefer-binary --timeout 120 -r "$MemReq"
    }

    if ($LASTEXITCODE -ne 0) {
        throw "Core Python package install failed with exit code $LASTEXITCODE. Please check your internet connection."
    }

    $installSec = [math]::Round($swInstall.Elapsed.TotalSeconds, 1)
    Write-Host "  [OK] [2/4] Core Python packages installed successfully (completed in $($installSec)s)" -ForegroundColor Green
}

# -----------------------------------------------------------------------------
# Part B: IGI Visual Companion HUD (PySide6 Desktop GUI - ~78 MB)
# -----------------------------------------------------------------------------
$probeIgi = & "$VenvPython" -c "try: import PySide6; print('ok')`nexcept: print('fail')"
if ($probeIgi -match "ok" -and !$Force) {
    Write-Host "  [OK] [2/4] IGI visual companion (PySide6) already installed." -ForegroundColor Green
} else {
    $installIgi = $false
    if ($WithIgi) {
        $installIgi = $true
    } elseif ($NoIgi) {
        $installIgi = $false
    } else {
        $isInteractive = [Environment]::UserInteractive -and (![Console]::IsInputRedirected)
        if ($isInteractive) {
            Write-Host ""
            Write-Host "  ============================================================" -ForegroundColor DarkCyan
            Write-Host "  [OPTIONAL COMPONENT] IGI Visual Companion HUD (The Eye)" -ForegroundColor Cyan
            Write-Host "  Enables on-screen Circle-to-Search (Ctrl+Shift+Q) & floating HUD." -ForegroundColor Gray
            Write-Host "  Requires PySide6-Essentials (~78 MB Qt runtime)." -ForegroundColor Gray
            Write-Host "  ============================================================" -ForegroundColor DarkCyan
            Write-Host "  (Recommended: Type 'Y' if you want the visual overlay layer," -ForegroundColor Yellow
            Write-Host "   or 'N' to keep setup ultra-fast in ~10s. You can always launch it" -ForegroundColor Gray
            Write-Host "   anytime later via scripts\launch_igi.bat)" -ForegroundColor Gray
            Write-Host ""
            $choice = Read-Host "  Install PySide6 for IGI Visual HUD now? [Y/n]"
            if ([string]::IsNullOrWhiteSpace($choice) -or $choice -match '^[Yy]') {
                $installIgi = $true
            } else {
                $installIgi = $false
                Write-Host "  [INFO] Skipping PySide6. (Run scripts\launch_igi.bat anytime to install)." -ForegroundColor Gray
            }
        } else {
            $installIgi = $false
        }
    }

    if ($installIgi) {
        Write-Host "  [2/4] Installing IGI Visual Companion (PySide6-Essentials)..." -ForegroundColor Cyan
        $swIgi = [System.Diagnostics.Stopwatch]::StartNew()
        if ($uvExe) {
            & $uvExe pip install --python "$VenvPython" -r "$IgiReq"
        } else {
            & "$VenvPython" -m pip install --prefer-binary --timeout 120 -r "$IgiReq"
        }
        if ($LASTEXITCODE -ne 0) {
            throw "PySide6 install failed with exit code $LASTEXITCODE. Please check your internet connection."
        }
        $igiSec = [math]::Round($swIgi.Elapsed.TotalSeconds, 1)
        Write-Host "  [OK] [2/4] IGI Visual Companion (PySide6) installed successfully (completed in $($igiSec)s)" -ForegroundColor Green
    }
}

Write-Host ""

# -----------------------------------------------------------------------------
# Step 3: Node.js Projects Compilation (CLI Bridge & Core Backend)
# -----------------------------------------------------------------------------
$needsBridge = $Force -or !(Test-NodeIsBuilt $CliBridgePath)
$needsCore = $Force -or !(Test-NodeIsBuilt $CoreDir)

if ($needsBridge) {
    Invoke-FastStep -Tag "[3/4]" -Title "Installing CLI bridge dependencies" -FileName "npm" -Arguments "install --no-audit --no-fund" -WorkingDirectory $CliBridgePath
    Invoke-FastStep -Tag "[3/4]" -Title "Compiling CLI bridge (TypeScript build)" -FileName "npm" -Arguments "run build" -WorkingDirectory $CliBridgePath
}

if ($needsCore) {
    Invoke-FastStep -Tag "[3/4]" -Title "Installing Enheduanna Core dependencies" -FileName "npm" -Arguments "install --no-audit --no-fund" -WorkingDirectory $CoreDir
    Invoke-FastStep -Tag "[3/4]" -Title "Compiling Enheduanna Core (TypeScript build)" -FileName "npm" -Arguments "run build" -WorkingDirectory $CoreDir
}

if (!$needsBridge -and !$needsCore) {
    Write-Host "  [OK] [3/4] Node.js projects already compiled (skipping, use -Force to rebuild)" -ForegroundColor Green
} else {
    Write-Host "  [OK] [3/4] Node.js projects compiled successfully." -ForegroundColor Green
}

Write-Host ""

# -----------------------------------------------------------------------------
# Step 4: Configuration Setup
# -----------------------------------------------------------------------------
$ConfigPath = Join-Path $RepoRoot "enheduanna.config.json"
$ConfigExample = Join-Path $RepoRoot "enheduanna.config.example.json"

if (!(Test-Path $ConfigPath)) {
    if (Test-Path $ConfigExample) {
        Copy-Item "$ConfigExample" "$ConfigPath"
        Write-Host "  [OK] [4/4] Generated enheduanna.config.json from portable template." -ForegroundColor Green
    }
} else {
    Write-Host "  [OK] [4/4] enheduanna.config.json is present." -ForegroundColor Green
}

Write-Host ""
Write-Host "======================================================" -ForegroundColor Green
Write-Host "  ENHEDUANNA SETUP COMPLETED SUCCESSFULLY!" -ForegroundColor Green
Write-Host "======================================================" -ForegroundColor Green
Write-Host ""
Write-Host "How to run the system:" -ForegroundColor White
Write-Host "  1. Set your Meta API Key (if not already set in shell):" -ForegroundColor Gray
Write-Host "     `$env:META_API_KEY = 'YOUR_KEY'" -ForegroundColor Yellow
Write-Host ""
Write-Host "  2. Launch Enheduanna Core Server & Dashboard (Port 4100):" -ForegroundColor Gray
Write-Host "     cd app\core; npm start" -ForegroundColor Yellow
Write-Host "     (Dashboard: http://127.0.0.1:4100)" -ForegroundColor Gray
Write-Host ""
Write-Host "  3. (Optional) Open MemVision Capture Monitoring Dashboard (Port 8765):" -ForegroundColor Gray
Write-Host "     cd memvison; .\.venv\Scripts\python.exe main.py ui" -ForegroundColor Yellow
Write-Host ""
Write-Host "  4. (Optional) Launch IGI Visual Companion HUD:" -ForegroundColor Gray
Write-Host "     .\scripts\launch_igi.bat" -ForegroundColor Yellow
Write-Host ""
