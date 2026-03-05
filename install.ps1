# RAPP Brainstem Installer for Windows
# Usage: irm https://raw.githubusercontent.com/kody-w/rapp-installer/main/install.ps1 | iex
#
# Works on a factory Windows 11 install — auto-installs Python, Git, and GitHub CLI via winget.

$ErrorActionPreference = "Stop"

$BRAINSTEM_HOME = "$env:USERPROFILE\.brainstem"
$BRAINSTEM_BIN = "$env:USERPROFILE\.local\bin"
$REPO_URL = "https://github.com/kody-w/rapp-installer.git"
$REMOTE_VERSION_URL = "https://raw.githubusercontent.com/kody-w/rapp-installer/main/rapp_brainstem/VERSION"

function Print-Banner {
    Write-Host ""
    Write-Host "  🧠 RAPP Brainstem" -ForegroundColor Cyan
    Write-Host "  Local-first AI agent server" -ForegroundColor Gray
    Write-Host "  Powered by GitHub Copilot — no API keys needed" -ForegroundColor Gray
    Write-Host ""
}

function Compare-SemVer {
    param([string]$Local, [string]$Remote)
    $lParts = $Local.Split('.')
    $rParts = $Remote.Split('.')
    for ($i = 0; $i -lt [Math]::Max($lParts.Length, $rParts.Length); $i++) {
        $lv = if ($i -lt $lParts.Length) { [int]$lParts[$i] } else { 0 }
        $rv = if ($i -lt $rParts.Length) { [int]$rParts[$i] } else { 0 }
        if ($rv -gt $lv) { return 1 }   # remote is newer
        if ($rv -lt $lv) { return -1 }  # local is newer
    }
    return 0  # equal
}

function Check-ForUpgrade {
    $versionFile = "$BRAINSTEM_HOME\src\rapp_brainstem\VERSION"

    if (-not (Test-Path $versionFile)) { return $true }

    $localVersion = (Get-Content $versionFile -Raw).Trim()

    try {
        $remoteVersion = (Invoke-WebRequest -Uri $REMOTE_VERSION_URL -UseBasicParsing -TimeoutSec 10).Content.Trim()
    } catch {
        Write-Host "  [!] Could not check remote version — upgrading anyway" -ForegroundColor Yellow
        return $true
    }

    Write-Host "  Local version:  $localVersion" -ForegroundColor Cyan
    Write-Host "  Remote version: $remoteVersion" -ForegroundColor Cyan

    if ($localVersion -eq $remoteVersion) {
        Write-Host ""
        Write-Host "  [OK] Already up to date (v$localVersion)" -ForegroundColor Green
        Write-Host ""
        return $false
    }

    $cmp = Compare-SemVer -Local $localVersion -Remote $remoteVersion
    if ($cmp -eq 1) {
        Write-Host "  [..] Upgrade available: $localVersion -> $remoteVersion" -ForegroundColor Yellow
        return $true
    }

    Write-Host ""
    Write-Host "  [OK] Already up to date (v$localVersion)" -ForegroundColor Green
    Write-Host ""
    return $false
}

function Install-WithWinget {
    param([string]$PackageId, [string]$Name)
    Write-Host "  [..] Installing $Name via winget..." -ForegroundColor Yellow
    winget install --id $PackageId --accept-source-agreements --accept-package-agreements --silent 2>&1 | Out-Null
    # Refresh PATH for this session
    $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path", "User")
}

function Check-Prerequisites {
    Write-Host "Checking prerequisites..."

    # winget (ships with Windows 11)
    try {
        winget --version 2>&1 | Out-Null
    } catch {
        Write-Host "  [X] winget not found — this installer requires Windows 10 1709+ or Windows 11" -ForegroundColor Red
        exit 1
    }

    # Git
    $gitOk = $false
    try {
        $gitVersion = git --version 2>&1
        if ($LASTEXITCODE -eq 0) {
            Write-Host "  [OK] $gitVersion" -ForegroundColor Green
            $gitOk = $true
        }
    } catch {}
    if (-not $gitOk) {
        Install-WithWinget "Git.Git" "Git"
        try {
            git --version 2>&1 | Out-Null
            Write-Host "  [OK] Git installed" -ForegroundColor Green
        } catch {
            Write-Host "  [X] Git install failed — install manually from https://git-scm.com" -ForegroundColor Red
            exit 1
        }
    }

    # Python 3.11+
    $pythonOk = $false
    try {
        $pythonVersion = python --version 2>&1
        if ($pythonVersion -match "Python 3\.(\d+)") {
            $minor = [int]$Matches[1]
            if ($minor -ge 11) {
                Write-Host "  [OK] $pythonVersion" -ForegroundColor Green
                $pythonOk = $true
            }
        }
    } catch {}
    if (-not $pythonOk) {
        Install-WithWinget "Python.Python.3.11" "Python 3.11"
        try {
            $pythonVersion = python --version 2>&1
            Write-Host "  [OK] $pythonVersion installed" -ForegroundColor Green
        } catch {
            Write-Host "  [X] Python install failed — install from https://python.org" -ForegroundColor Red
            exit 1
        }
    }

    # GitHub CLI (optional but recommended)
    try {
        gh --version 2>&1 | Out-Null
        Write-Host "  [OK] GitHub CLI installed" -ForegroundColor Green
    } catch {
        Write-Host "  [..] Installing GitHub CLI..." -ForegroundColor Yellow
        Install-WithWinget "GitHub.cli" "GitHub CLI"
        try {
            gh --version 2>&1 | Out-Null
            Write-Host "  [OK] GitHub CLI installed" -ForegroundColor Green
        } catch {
            Write-Host "  [!] GitHub CLI not installed (optional — you can authenticate later)" -ForegroundColor Yellow
        }
    }
}

function Install-Brainstem {
    Write-Host ""
    Write-Host "Installing RAPP Brainstem..."

    if (-not (Test-Path $BRAINSTEM_HOME)) {
        New-Item -ItemType Directory -Force -Path $BRAINSTEM_HOME | Out-Null
    }

    if (Test-Path "$BRAINSTEM_HOME\src\.git") {
        Write-Host "  Updating existing installation..."
        Push-Location "$BRAINSTEM_HOME\src"
        try { git pull --quiet 2>&1 | Out-Null } catch {}
        Pop-Location
    } else {
        if (Test-Path "$BRAINSTEM_HOME\src") {
            Remove-Item -Recurse -Force "$BRAINSTEM_HOME\src" -ErrorAction SilentlyContinue
        }
        Write-Host "  Cloning repository..."
        git clone --quiet $REPO_URL "$BRAINSTEM_HOME\src" 2>&1
        if ($LASTEXITCODE -ne 0) {
            Write-Host "  [X] Failed to clone repository" -ForegroundColor Red
            exit 1
        }
    }
    Write-Host "  [OK] Source code ready" -ForegroundColor Green
}

function Setup-Dependencies {
    Write-Host ""
    Write-Host "Installing dependencies..."
    Push-Location "$BRAINSTEM_HOME\src\rapp_brainstem"
    python -m pip install -r requirements.txt --quiet 2>&1 | Out-Null
    Pop-Location
    Write-Host "  [OK] Dependencies installed" -ForegroundColor Green
}

function Install-CLI {
    Write-Host ""
    Write-Host "Installing CLI..."

    if (-not (Test-Path $BRAINSTEM_BIN)) {
        New-Item -ItemType Directory -Force -Path $BRAINSTEM_BIN | Out-Null
    }

    # Batch wrapper (works in cmd.exe and PowerShell)
    $cmdContent = @"
@echo off
cd /d "$BRAINSTEM_HOME\src\rapp_brainstem"
python brainstem.py %*
"@
    Set-Content -Path "$BRAINSTEM_BIN\brainstem.cmd" -Value $cmdContent

    # PowerShell wrapper
    $psContent = @"
Set-Location "$BRAINSTEM_HOME\src\rapp_brainstem"
python brainstem.py @args
"@
    Set-Content -Path "$BRAINSTEM_BIN\brainstem.ps1" -Value $psContent

    # Add to PATH if not already there
    $userPath = [Environment]::GetEnvironmentVariable("Path", "User")
    if ($userPath -notlike "*$BRAINSTEM_BIN*") {
        [Environment]::SetEnvironmentVariable("Path", "$BRAINSTEM_BIN;$userPath", "User")
        $env:Path = "$BRAINSTEM_BIN;$env:Path"
        Write-Host "  Added to PATH" -ForegroundColor Green
    }

    Write-Host "  [OK] CLI installed" -ForegroundColor Green
}

function Create-Env {
    $envFile = "$BRAINSTEM_HOME\src\rapp_brainstem\.env"
    $exampleFile = "$BRAINSTEM_HOME\src\rapp_brainstem\.env.example"
    if (-not (Test-Path $envFile) -and (Test-Path $exampleFile)) {
        Copy-Item $exampleFile $envFile
    }
}

function Main {
    Print-Banner

    # Check if this is an upgrade of an existing install
    if (Test-Path "$BRAINSTEM_HOME\src\.git") {
        Write-Host "Checking for updates..."
        if (-not (Check-ForUpgrade)) {
            return
        }
    }

    Check-Prerequisites
    Install-Brainstem
    Setup-Dependencies
    Install-CLI
    Create-Env

    $installedVersion = ""
    $vf = "$BRAINSTEM_HOME\src\rapp_brainstem\VERSION"
    if (Test-Path $vf) { $installedVersion = (Get-Content $vf -Raw).Trim() }

    Write-Host ""
    Write-Host "===================================================" -ForegroundColor Cyan
    Write-Host "  [OK] RAPP Brainstem v$installedVersion installed!" -ForegroundColor Green
    Write-Host "===================================================" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "  Get started:"
    Write-Host "    gh auth login        " -NoNewline; Write-Host "# authenticate with GitHub" -ForegroundColor Gray
    Write-Host "    brainstem            " -NoNewline; Write-Host "# start the server (localhost:7071)" -ForegroundColor Gray
    Write-Host ""
    Write-Host "  Then open http://localhost:7071 in your browser."
    Write-Host ""
}

Main
