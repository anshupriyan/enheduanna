# Enheduanna End-to-End Environment Setup Script
# Features zero-overhead spinner animations, branch-locked cli-bridge setup, and high-speed uv/mirror package resolution.

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
# Runs commands in native child processes with an async 100ms visual spinner
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
        if (Test-Path $localUv) { $uvCmd = $localUv }
    }

    # 2. Check python binaries
    $pyExec = $null
    $pyCmd = Get-Command python -ErrorAction SilentlyContinue
    if ($pyCmd -and $pyCmd.Source -notlike "*WindowsApps*") {
        try {
            $v = & python --version 2>&1
            if ($v -match "Python 3\.") { $pyExec = "python" }
        } catch {}
    }

    if (!$pyExec) {
        $pyLauncher = Get-Command py -ErrorAction SilentlyContinue
        if ($pyLauncher) {
            try {
                $v = & py -3 --version 2>&1
                if ($v -match "Python 3\.") { $pyExec = "py" }
            } catch {}
        }
    }

    if (!$pyExec) {
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
                $pyExec = $found[0].FullName
                break
            }
        }
    }

    if (!$pyExec) {
        $siblingVenv = Join-Path $RepoRoot "..\memvison\.venv\Scripts\python.exe"
        if (Test-Path $siblingVenv) { $pyExec = $siblingVenv }
    }

    return @{ Python = $pyExec; UV = $uvCmd }
}

$engines = Find-FastPythonEngine
if (!$engines.Python) {
    Write-Host "  [FAIL] Python 3.10+ was not found on this system. Please install Python 3.10+." -ForegroundColor Red
    exit 1
}

$pyVerStr = (& $engines.Python --version 2>&1).Trim()
Write-Host "  [OK] Python: $pyVerStr" -ForegroundColor Green

if ($engines.UV) {
    Write-Host "  [OK] High-Speed Engine: uv detected (blazing fast parallel package installer)" -ForegroundColor Cyan
} else {
    Write-Host "  [INFO] High-Speed Engine: uv not found (falling back to optimized pip with binary wheels)" -ForegroundColor Gray
}

Write-Host ""

# -----------------------------------------------------------------------------
# Step 1: External Dependency cli-bridge (Branch: meta-hackathon)
# -----------------------------------------------------------------------------
if (!(Test-Path $CliBridgePath)) {
    Invoke-StepWithSpinner -Tag "[1/4]" -Title "Cloning cli-bridge (branch: meta-hackathon)" -FileName "git" -Arguments "clone -b meta-hackathon https://github.com/anshupriyan/cli-bridge.git `"$CliBridgePath`""
} else {
    Invoke-StepWithSpinner -Tag "[1/4]" -Title "Verifying cli-bridge branch (meta-hackathon)" -FileName "git" -Arguments "-C `"$CliBridgePath`" checkout meta-hackathon"
}

Invoke-StepWithSpinner -Tag "[1/4]" -Title "Installing cli-bridge dependencies (npm install)" -FileName "cmd.exe" -Arguments "/c npm install" -WorkingDirectory $CliBridgePath

Invoke-StepWithSpinner -Tag "[1/4]" -Title "Compiling cli-bridge TypeScript (npm run build)" -FileName "cmd.exe" -Arguments "/c npm run build" -WorkingDirectory $CliBridgePath

Write-Host ""

# -----------------------------------------------------------------------------
# Step 2: High-Speed Python Virtual Environment (MemVision + IGI)
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

# Install dependencies using UV or Optimized Pip
if ($engines.UV) {
    $uvExe = if ($engines.UV -is [string]) { $engines.UV } else { $engines.UV.Source }
    $mirrorArg = if ($env:PIP_INDEX_URL) { "--index-url $env:PIP_INDEX_URL" } else { "" }
    Invoke-StepWithSpinner -Tag "[2/4]" -Title "Installing Python dependencies via uv (parallel binary streams)" -FileName $uvExe -Arguments "pip install --python `"$VenvPython`" $mirrorArg -r `"$MemReq`" -r `"$IgiReq`""
} else {
    $mirrorArg = if ($env:PIP_INDEX_URL) { "-i $env:PIP_INDEX_URL" } else { "" }
    Invoke-StepWithSpinner -Tag "[2/4]" -Title "Installing Python dependencies (pip with binary wheel preference)" -FileName $VenvPython -Arguments "-m pip install --quiet --prefer-binary --timeout 30 $mirrorArg -r `"$MemReq`" -r `"$IgiReq`""
}

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
