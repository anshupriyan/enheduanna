# Enheduanna End-to-End Environment Setup Script
# Zero-deadlock spinner execution, native download streaming, branch-locked cli-bridge, and high-speed uv package resolution.

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

Write-Host "======================================================" -ForegroundColor Cyan
Write-Host "  ENHEDUANNA - Autonomous Desktop AI Framework Setup" -ForegroundColor White
Write-Host "======================================================" -ForegroundColor Cyan

$RepoRoot = (Resolve-Path "$PSScriptRoot\..").Path
$CliBridgePath = (Join-Path $RepoRoot "..\cli-bridge")

Write-Host "  Repository Root: $RepoRoot" -ForegroundColor Gray
Write-Host "  External CLI Bridge: $CliBridgePath" -ForegroundColor Gray
Write-Host ""

# -----------------------------------------------------------------------------
# Zero-Overhead Deadlock-Free Spinner Execution Engine
# Uses temporary log files for stdout/stderr to completely eliminate Windows pipe buffer deadlocks
# -----------------------------------------------------------------------------
function Invoke-StepWithSpinner {
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

# Python & UV Engine Resolution
function Find-FastPythonEngine {
    # 1. Check for uv package runner (ultra-fast, 10x-50x speedup)
    $uvCmd = Get-Command uv -ErrorAction SilentlyContinue
    if (!$uvCmd) {
        $localUv = "$env:USERPROFILE\.local\bin\uv.exe"
        if (Test-Path $localUv) {
            $uvCmd = $localUv
        }
    }

    # 2. Check for Python binary (must be >= 3.10)
    $pyCmd = $null

    # First check via UV if available (prefer 3.12/3.11 for universal wheel support)
    if ($uvCmd) {
        try {
            $uvExe = if ($uvCmd -is [string]) { $uvCmd } else { $uvCmd.Source }
            $uvPy = (& $uvExe python find 3.12 2>$null).Trim()
            if (!$uvPy) { $uvPy = (& $uvExe python find 3.11 2>$null).Trim() }
            if (!$uvPy) { $uvPy = (& $uvExe python find 3.10 2>$null).Trim() }
            if ($uvPy -and (Test-Path $uvPy)) {
                $pyCmd = $uvPy
            }
        } catch {}
    }

    # Second check standard UV python directories
    if (!$pyCmd) {
        $uvPythons = Get-ChildItem "$env:APPDATA\uv\python\cpython-3.12*\python.exe" -ErrorAction SilentlyContinue
        if (!$uvPythons) {
            $uvPythons = Get-ChildItem "$env:APPDATA\uv\python\*\python.exe" -ErrorAction SilentlyContinue
        }
        if ($uvPythons) {
            foreach ($p in $uvPythons) {
                $test = & $p.FullName -c "import sys; print(1 if sys.version_info >= (3, 10) else 0)" 2>$null
                if ($test -match "1") {
                    $pyCmd = $p.FullName
                    break
                }
            }
        }
    }

    # Third check PATH and common install locations
    if (!$pyCmd) {
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
                    # Verify >= 3.10 (ignore 0.0.0.0 WindowsApps stubs)
                    $test = & "$p" -c "import sys; print(1 if sys.version_info >= (3, 10) else 0)" 2>$null
                    if ($test -match "1") {
                        $pyCmd = $p
                        break
                    }
                }
            } catch {}
        }
    }

    # If UV is available but no Python 3.10+ found, auto-install Python 3.12
    if (!$pyCmd -and $uvCmd) {
        $uvExe = if ($uvCmd -is [string]) { $uvCmd } else { $uvCmd.Source }
        Write-Host "  [INFO] Installing Python 3.12 via uv..." -ForegroundColor Cyan
        & $uvExe python install 3.12
        $pyCmd = (& $uvExe python find 3.12 2>$null).Trim()
    }

    return @{ UV = $uvCmd; Python = $pyCmd }
}

$engines = Find-FastPythonEngine

if (!$engines.Python) {
    Write-Host "  [FAIL] Python 3.10+ not found in PATH or standard install locations." -ForegroundColor Red
    Write-Host "         Please install Python 3.10+ from https://www.python.org/downloads/ (check 'Add to PATH')." -ForegroundColor Yellow
    exit 1
}

$pyVersion = (& $engines.Python --version 2>&1).Trim()
Write-Host "  [OK] Python: $pyVersion" -ForegroundColor Green

if ($engines.UV) {
    Write-Host "  [OK] High-Speed Engine: uv detected (blazing fast parallel package installer)" -ForegroundColor Green
} else {
    Write-Host "  [INFO] uv not detected. Running standard pip resolver (tip: run 'pip install uv' for 10x faster installs)." -ForegroundColor DarkYellow
}

Write-Host ""

# -----------------------------------------------------------------------------
# Step 1: External CLI Bridge Repository Setup
# Strictly locks to branch: meta-hackathon
# -----------------------------------------------------------------------------
if (!(Test-Path $CliBridgePath)) {
    Invoke-StepWithSpinner -Tag "[1/4]" -Title "Cloning cli-bridge (branch: meta-hackathon)" -FileName "git" -Arguments "clone -b meta-hackathon https://github.com/anshupriyan/cli-bridge.git `"$CliBridgePath`""
} else {
    Invoke-StepWithSpinner -Tag "[1/4]" -Title "Verifying cli-bridge branch (meta-hackathon)" -FileName "git" -Arguments "checkout meta-hackathon" -WorkingDirectory $CliBridgePath
    Invoke-StepWithSpinner -Tag "[1/4]" -Title "Pulling latest cli-bridge updates" -FileName "git" -Arguments "pull origin meta-hackathon" -WorkingDirectory $CliBridgePath
}

Invoke-StepWithSpinner -Tag "[1/4]" -Title "Installing cli-bridge dependencies (npm install)" -FileName "cmd.exe" -Arguments "/c npm install" -WorkingDirectory $CliBridgePath

Invoke-StepWithSpinner -Tag "[1/4]" -Title "Compiling cli-bridge TypeScript (npm run build)" -FileName "cmd.exe" -Arguments "/c npm run build" -WorkingDirectory $CliBridgePath

Write-Host ""

# -----------------------------------------------------------------------------
# Step 2: High-Speed Python Virtual Environment (MemVision + IGI)
# Displays live download streaming (package names, progress %, and transfer speed)
# -----------------------------------------------------------------------------
$VenvDir = Join-Path $RepoRoot "memvison\.venv"
$VenvPython = Join-Path $VenvDir "Scripts\python.exe"
$MemReq = Join-Path $RepoRoot "memvison\requirements.txt"
$IgiReq = Join-Path $RepoRoot "igi\requirements.txt"

# Create venv if not present
if (!(Test-Path $VenvPython)) {
    if ($engines.UV) {
        $uvExe = if ($engines.UV -is [string]) { $engines.UV } else { $engines.UV.Source }
        Invoke-StepWithSpinner -Tag "[2/4]" -Title "Creating virtual environment with uv (instant)" -FileName $uvExe -Arguments "venv `"$VenvDir`" --python `"$($engines.Python)`""
    } else {
        Invoke-StepWithSpinner -Tag "[2/4]" -Title "Creating virtual environment (python -m venv)" -FileName $engines.Python -Arguments "-m venv `"$VenvDir`""
    }
} else {
    Write-Host "  [OK] [2/4] Virtual environment exists at memvison\.venv" -ForegroundColor Green
}

Write-Host "  [2/4] Installing Python packages (showing live download stream)..." -ForegroundColor Cyan

$swInstall = [System.Diagnostics.Stopwatch]::StartNew()
$env:UV_HTTP_TIMEOUT = "120"

if ($engines.UV) {
    $uvExe = if ($engines.UV -is [string]) { $engines.UV } else { $engines.UV.Source }
    & $uvExe pip install --python "$VenvPython" -r "$MemReq" -r "$IgiReq"
} else {
    & "$VenvPython" -m pip install --prefer-binary --timeout 120 -r "$MemReq" -r "$IgiReq"
}

if ($LASTEXITCODE -ne 0) {
    throw "Python package install failed with exit code $LASTEXITCODE. Please check your internet connection and re-run setup.bat."
}

$installSec = [math]::Round($swInstall.Elapsed.TotalSeconds, 1)
Write-Host "  [OK] [2/4] Python packages installed successfully (completed in $($installSec)s)" -ForegroundColor Green

Write-Host ""

# -----------------------------------------------------------------------------
# Step 3: Enheduanna Core & Dashboard Compilation
# -----------------------------------------------------------------------------
$CoreDir = Join-Path $RepoRoot "app\core"

Invoke-StepWithSpinner -Tag "[3/4]" -Title "Installing Enheduanna Core dependencies (npm install)" -FileName "cmd.exe" -Arguments "/c npm install" -WorkingDirectory $CoreDir

Invoke-StepWithSpinner -Tag "[3/4]" -Title "Building Enheduanna Core backend (npm run build)" -FileName "cmd.exe" -Arguments "/c npm run build" -WorkingDirectory $CoreDir

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
