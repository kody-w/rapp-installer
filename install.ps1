# RAPP Brainstem Installer for Windows
# Usage: irm https://raw.githubusercontent.com/kody-w/rapp-installer/main/install.ps1 | iex

$ErrorActionPreference = "Stop"

$BRAINSTEM_HOME = "$env:USERPROFILE\.brainstem"
$BRAINSTEM_BIN = "$env:USERPROFILE\.local\bin"
$REPO_URL = "https://github.com/kody-w/rapp-installer.git"

function Print-Banner {
    Write-Host ""
    Write-Host "  RAPP Brainstem" -ForegroundColor Cyan
    Write-Host "  Local-first AI agent server" -ForegroundColor Gray
    Write-Host "  Powered by GitHub Copilot" -ForegroundColor Gray
    Write-Host ""
}

function Check-Prerequisites {
    Write-Host "Checking prerequisites..."

    # Python 3.11+
    try {
        $pythonVersion = python --version 2>&1
        if ($pythonVersion -match "Python 3\.(\d+)") {
            $minor = [int]$Matches[1]
            if ($minor -ge 11) {
                Write-Host "  [OK] $pythonVersion" -ForegroundColor Green
            } else {
                throw "Too old"
            }
        } else {
            throw "Cannot parse"
        }
    } catch {
        Write-Host "  [X] Python 3.11+ required" -ForegroundColor Red
        Write-Host "      Install from https://python.org"
        exit 1
    }

    # Git
    try {
        $gitVersion = git --version 2>&1
        Write-Host "  [OK] $gitVersion" -ForegroundColor Green
    } catch {
        Write-Host "  [X] Git required" -ForegroundColor Red
        Write-Host "      Install from https://git-scm.com"
        exit 1
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

    # Batch wrapper
    $cmdContent = @"
@echo off
cd /d "$BRAINSTEM_HOME\src\rapp_brainstem"
python brainstem.py %*
"@
    Set-Content -Path "$BRAINSTEM_BIN\brainstem.cmd" -Value $cmdContent

    # PowerShell wrapper
    $psContent = @"
Set-Location "$BRAINSTEM_HOME\src\rapp_brainstem"
python brainstem.py `$args
"@
    Set-Content -Path "$BRAINSTEM_BIN\brainstem.ps1" -Value $psContent

    # Add to PATH
    $userPath = [Environment]::GetEnvironmentVariable("Path", "User")
    if ($userPath -notlike "*$BRAINSTEM_BIN*") {
        [Environment]::SetEnvironmentVariable("Path", "$BRAINSTEM_BIN;$userPath", "User")
        Write-Host "  Added $BRAINSTEM_BIN to PATH" -ForegroundColor Green
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
    Check-Prerequisites
    Install-Brainstem
    Setup-Dependencies
    Install-CLI
    Create-Env

    Write-Host ""
    Write-Host "===================================================" -ForegroundColor Cyan
    Write-Host "  [OK] RAPP Brainstem installed!" -ForegroundColor Green
    Write-Host "===================================================" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "  Get started (open a NEW terminal):"
    Write-Host "    gh auth login        # authenticate with GitHub"
    Write-Host "    brainstem            # start the server (localhost:7071)"
    Write-Host ""
    Write-Host "  Then open http://localhost:7071 in your browser."
    Write-Host ""
}

Main
