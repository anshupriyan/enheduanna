param(
    [switch]$FastMirror,
    [string]$IndexUrl = ""
)

# Enheduanna End-to-End Environment Setup Script
# Features zero-overhead spinner animations, live package download streaming, branch-locked cli-bridge, and high-speed uv package resolution.

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
# Zero-Overhead Spinner Execution Engine
# Runs silent builds/checks with an async 100ms visual spinner
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

    $pinfo = New-Object System.Diagnostics.ProcessStartInfo
    $pinfo.FileName = $FileName
    $pinfo.Arguments = $Arguments
    $pinfo.WorkingDirectory = $WorkingDirectory
    $pinfo.UseShellExecute = $false
    $pinfo.RedirectStandardOutput = $true
    $pinfo.RedirectStandardError = $true
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
    $stdout = $proc.StandardOutput.ReadToEnd()
    $stderr = $proc.StandardError.ReadToEnd()
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

    # 2. Check for Python binary
    $pyCmd = $null

    # First check via UV if available
    if ($uvCmd) {
        try {
            $uvExe = if ($uvCmd -is [string]) { $uvCmd } else { $uvCmd.Source }
            $uvPy = (& $uvExe python find 3.12 2>$null).Trim()
            if (!$uvPy) { $uvPy = (& $uvExe python find 2>$null).Trim() }
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
            $pyCmd = ($uvPythons | Select-Object -First 1).FullName
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
                    # Test execution (ignore 0.0.0.0 WindowsApps stubs)
                    $test = & "$p" -c "import sys; print(sys.version_info.major)" 2>$null
                    if ($test -match "3") {
                        $pyCmd = $p
                        break
                    }
                }
            } catch {}
        }
    }

    return @{ UV = $uvCmd; Python = $pyCmd }
}

$engines = Find-FastPythonEngine

if (!$engines.Python) {
    Write-Host "  [FAIL] Python 3.10+ not found in PATH or standard install locations." -ForegroundColor Red
    Write-Host "         Please install Python from https://www.python.org/downloads/ (check 'Add to PATH')." -ForegroundColor Yellow
    exit 1
}

$pyVersion = (& $engines.Python --version 2>&1).Trim()
Write-Host "  [OK] Python: $pyVersion" -ForegroundColor Green

if ($engines.UV) {
    Write-Host "  [OK] High-Speed Engine: uv detected (blazing fast parallel package installer)" -ForegroundColor Green
} else {
    Write-Host "  [INFO] uv not detected. Running standard optimized pip resolver." -ForegroundColor DarkYellow
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

# Resolve Mirror (Default, User-specified, FastMirror, or PIP_INDEX_URL)
$resolvedIndex = ""
if ($IndexUrl) {
    $resolvedIndex = $IndexUrl
} elseif ($FastMirror) {
    $resolvedIndex = "https://mirrors.aliyun.com/pypi/simple/"
} elseif ($env:PIP_INDEX_URL) {
    $resolvedIndex = $env:PIP_INDEX_URL
}

Write-Host "  [2/4] Installing Python packages (showing live download stream)..." -ForegroundColor Cyan
if ($resolvedIndex) {
    Write-Host "        Mirror: $resolvedIndex" -ForegroundColor DarkCyan
}

$swInstall = [System.Diagnostics.Stopwatch]::StartNew()

if ($engines.UV) {
    $uvExe = if ($engines.UV -is [string]) { $engines.UV } else { $engines.UV.Source }
    $mirrorArgs = @()
    if ($resolvedIndex) {
        $mirrorArgs += @("--index-url", $resolvedIndex)
    }

    & $uvExe pip install --python "$VenvPython" @mirrorArgs -r "$MemReq" -r "$IgiReq"
    if ($LASTEXITCODE -ne 0) {
        # If default PyPI failed or timed out and no mirror was forced, auto-fallback to high-speed CDN mirror
        if (!$resolvedIndex) {
            Write-Host "  [WARN] Default PyPI connection slow or timed out. Auto-switching to high-speed CDN mirror..." -ForegroundColor Yellow
            & $uvExe pip install --python "$VenvPython" --index-url "https://mirrors.aliyun.com/pypi/simple/" -r "$MemReq" -r "$IgiReq"
            if ($LASTEXITCODE -ne 0) {
                throw "Python package installation failed with exit code $LASTEXITCODE"
            }
        } else {
            throw "Python package installation failed with exit code $LASTEXITCODE"
        }
    }
} else {
    $mirrorArgs = @()
    if ($resolvedIndex) {
        $mirrorArgs += @("-i", $resolvedIndex)
    }

    & "$VenvPython" -m pip install --prefer-binary --timeout 30 @mirrorArgs -r "$MemReq" -r "$IgiReq"
    if ($LASTEXITCODE -ne 0) {
        if (!$resolvedIndex) {
            Write-Host "  [WARN] Default PyPI connection slow or timed out. Auto-switching to high-speed CDN mirror..." -ForegroundColor Yellow
            & "$VenvPython" -m pip install --prefer-binary --timeout 30 -i "https://mirrors.aliyun.com/pypi/simple/" -r "$MemReq" -r "$IgiReq"
            if ($LASTEXITCODE -ne 0) {
                throw "Python package installation failed with exit code $LASTEXITCODE"
            }
        } else {
            throw "Python package installation failed with exit code $LASTEXITCODE"
        }
    }
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
Write-Host "     cd memvison; .\venv\Scripts\python.exe main.py ui" -ForegroundColor Yellow
Write-Host ""
Write-Host "  4. (Optional) Launch IGI Visual Companion HUD:" -ForegroundColor Gray
Write-Host "     .\scripts\launch_igi.bat" -ForegroundColor Yellow
Write-Host ""
