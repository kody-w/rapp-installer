# RAPP Installer for Windows
# https://github.com/kody-w/rapp-installer
#
# Install:
#   irm https://raw.githubusercontent.com/kody-w/rapp-installer/main/install.ps1 | iex
#
# Or download and run:
#   .\install.ps1

$ErrorActionPreference = "Stop"

$RAPP_HOME = "$env:USERPROFILE\.rapp"
$RAPP_BIN = "$env:USERPROFILE\.local\bin"
$RAPP_REPO = "https://github.com/kody-w/RAPPAI.git"

function Print-Banner {
    Write-Host ""
    Write-Host "  RAPP - Rapid AI Agent Production Pipeline" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "  ██████╗  █████╗ ██████╗ ██████╗ " -ForegroundColor Cyan
    Write-Host "  ██╔══██╗██╔══██╗██╔══██╗██╔══██╗" -ForegroundColor Cyan
    Write-Host "  ██████╔╝███████║██████╔╝██████╔╝" -ForegroundColor Cyan
    Write-Host "  ██╔══██╗██╔══██║██╔═══╝ ██╔═══╝ " -ForegroundColor Cyan
    Write-Host "  ██║  ██║██║  ██║██║     ██║     " -ForegroundColor Cyan
    Write-Host "  ╚═╝  ╚═╝╚═╝  ╚═╝╚═╝     ╚═╝     " -ForegroundColor Cyan
    Write-Host ""
}

function Check-Prerequisites {
    Write-Host "Checking prerequisites..."

    # Check Python
    try {
        $pythonVersion = python --version 2>&1
        if ($pythonVersion -match "Python 3\.(\d+)") {
            $minor = [int]$Matches[1]
            if ($minor -ge 11) {
                Write-Host "  [OK] $pythonVersion" -ForegroundColor Green
            } else {
                Write-Host "  [X] Python 3.11+ required (found $pythonVersion)" -ForegroundColor Red
                Write-Host "      Install from https://python.org"
                exit 1
            }
        } else {
            throw "Cannot parse Python version"
        }
    } catch {
        Write-Host "  [X] Python 3.11+ required" -ForegroundColor Red
        Write-Host "      Install from https://python.org"
        exit 1
    }

    # Check Git
    try {
        $gitVersion = git --version 2>&1
        Write-Host "  [OK] $gitVersion" -ForegroundColor Green
    } catch {
        Write-Host "  [X] Git required" -ForegroundColor Red
        Write-Host "      Install from https://git-scm.com"
        exit 1
    }

    # Check Azure CLI (optional)
    try {
        $azVersion = az --version 2>&1 | Select-Object -First 1
        Write-Host "  [OK] Azure CLI installed" -ForegroundColor Green
    } catch {
        Write-Host "  [!] Azure CLI not found (required for setup)" -ForegroundColor Yellow
        Write-Host "      Install later: https://aka.ms/installazurecli"
    }
}

function Setup-GitHubAuth {
    Write-Host ""
    Write-Host "GitHub Authentication Required" -ForegroundColor Yellow
    Write-Host "RAPP source code is in a private repository."
    Write-Host ""

    # Check if gh CLI is available
    try {
        $ghAuth = gh auth status 2>&1
        if ($LASTEXITCODE -eq 0) {
            Write-Host "  [OK] Already authenticated with GitHub CLI" -ForegroundColor Green
            return
        }
    } catch {
        # gh not installed, continue with other methods
    }

    # Test if we can access the repo
    try {
        $testAccess = git ls-remote $RAPP_REPO 2>&1
        if ($LASTEXITCODE -eq 0) {
            Write-Host "  [OK] Git credentials found" -ForegroundColor Green
            return
        }
    } catch {
        # No access, continue
    }

    Write-Host "Options to authenticate:"
    Write-Host ""
    Write-Host "  1. Install GitHub CLI (recommended):"
    Write-Host "     winget install GitHub.cli"
    Write-Host "     gh auth login"
    Write-Host ""
    Write-Host "  2. Use HTTPS with personal access token"
    Write-Host "     When prompted, enter your GitHub username and PAT as password"
    Write-Host ""

    $hasAuth = Read-Host "Do you have GitHub access configured? (y/n)"

    if ($hasAuth -notin @("y", "Y")) {
        Write-Host ""
        Write-Host "To get access:"
        Write-Host "  1. Request access to github.com/kody-w/RAPP"
        Write-Host "  2. Create a Personal Access Token: https://github.com/settings/tokens"
        Write-Host "  3. Run this installer again"
        exit 1
    }
}

function Install-RAPP {
    Write-Host ""
    Write-Host "Installing RAPP..."

    # Create RAPP home directory
    if (-not (Test-Path $RAPP_HOME)) {
        New-Item -ItemType Directory -Force -Path $RAPP_HOME | Out-Null
    }

    # Clone or update repo
    if (Test-Path "$RAPP_HOME\src\.git") {
        Write-Host "  Updating existing installation..."
        Push-Location "$RAPP_HOME\src"
        try {
            git pull --quiet 2>&1 | Out-Null
        } catch {
            Write-Host "  Warning: Could not update, using existing version" -ForegroundColor Yellow
        }
        Pop-Location
    } else {
        Write-Host "  Cloning repository (this may prompt for credentials)..."

        # Remove existing src if it's not a git repo
        if (Test-Path "$RAPP_HOME\src") {
            Remove-Item -Recurse -Force "$RAPP_HOME\src" -ErrorAction SilentlyContinue
        }

        try {
            git clone --quiet $RAPP_REPO "$RAPP_HOME\src" 2>&1
            if ($LASTEXITCODE -ne 0) {
                throw "Git clone failed"
            }
        } catch {
            Write-Host "  [X] Failed to clone repository" -ForegroundColor Red
            Write-Host ""
            Write-Host "  Possible causes:"
            Write-Host "    - No access to private repository"
            Write-Host "    - Invalid credentials"
            Write-Host "    - Network issues"
            Write-Host ""
            Write-Host "  Request access at: github.com/kody-w/RAPP"
            exit 1
        }
    }
    Write-Host "  [OK] Source code ready" -ForegroundColor Green
}

function Setup-Environment {
    Write-Host ""
    Write-Host "Setting up Python environment..."

    Push-Location $RAPP_HOME

    # Create virtual environment
    if (-not (Test-Path "venv")) {
        python -m venv venv
    }

    # Activate and install dependencies
    & ".\venv\Scripts\Activate.ps1"

    # Upgrade pip
    pip install --upgrade pip --quiet 2>&1 | Out-Null

    # Install dependencies
    Write-Host "  Installing dependencies (this may take a moment)..."
    if (Test-Path "src\requirements.txt") {
        pip install -r src\requirements.txt --quiet 2>&1 | Out-Null
    }

    Pop-Location
    Write-Host "  [OK] Dependencies installed" -ForegroundColor Green
}

function Install-CLI {
    Write-Host ""
    Write-Host "Installing CLI..."

    # Create bin directory
    if (-not (Test-Path $RAPP_BIN)) {
        New-Item -ItemType Directory -Force -Path $RAPP_BIN | Out-Null
    }

    # Create batch file wrapper
    $wrapperContent = @"
@echo off
set RAPP_HOME=%USERPROFILE%\.rapp

REM Activate virtual environment
call "%RAPP_HOME%\venv\Scripts\activate.bat"

REM Set Python path
set PYTHONPATH=%RAPP_HOME%\src;%PYTHONPATH%

REM Run CLI
python -m rapp_cli %*
"@

    Set-Content -Path "$RAPP_BIN\rapp.cmd" -Value $wrapperContent

    # Also create PowerShell wrapper for PS users
    $psWrapperContent = @"
`$env:RAPP_HOME = "`$env:USERPROFILE\.rapp"
& "`$env:RAPP_HOME\venv\Scripts\Activate.ps1"
`$env:PYTHONPATH = "`$env:RAPP_HOME\src;`$env:PYTHONPATH"
python -m rapp_cli `$args
"@

    Set-Content -Path "$RAPP_BIN\rapp.ps1" -Value $psWrapperContent

    # Add to PATH if not already there
    $userPath = [Environment]::GetEnvironmentVariable("Path", "User")
    if ($userPath -notlike "*$RAPP_BIN*") {
        [Environment]::SetEnvironmentVariable("Path", "$RAPP_BIN;$userPath", "User")
        Write-Host "  Added $RAPP_BIN to PATH" -ForegroundColor Green
    }

    Write-Host "  [OK] CLI installed to $RAPP_BIN\rapp.cmd" -ForegroundColor Green
}

# Main installation
function Main {
    Print-Banner
    Check-Prerequisites
    Setup-GitHubAuth
    Install-RAPP
    Setup-Environment
    Install-CLI

    Write-Host ""
    Write-Host "===================================================" -ForegroundColor Cyan
    Write-Host "  [OK] RAPP installed successfully!" -ForegroundColor Green
    Write-Host "===================================================" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "  Get started (open a NEW terminal first):"
    Write-Host "    rapp              Start RAPP (opens web UI)"
    Write-Host "    rapp setup        Configure Azure connection"
    Write-Host "    rapp --help       Show all commands"
    Write-Host ""
}

# Run main
Main
