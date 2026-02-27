# CommunityRAPP — One-line installer for Windows
# Usage: irm https://raw.githubusercontent.com/kody-w/rapp-installer/main/community_rapp/install.ps1 | iex
#
# Requires: GitHub CLI (gh) authenticated with access to kody-w/CommunityRAPP

$ErrorActionPreference = "Stop"

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  CommunityRAPP - Local Setup" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# ── Prerequisites ────────────────────────────────────────────
Write-Host "Checking prerequisites..." -ForegroundColor Yellow

# GitHub CLI
if (-not (Get-Command gh -ErrorAction SilentlyContinue)) {
    Write-Host "Installing GitHub CLI..." -ForegroundColor Yellow
    winget install GitHub.cli --accept-source-agreements --accept-package-agreements
    $env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")
}
Write-Host "[OK] GitHub CLI" -ForegroundColor Green

# Check gh auth
$ghStatus = gh auth status 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "Not logged into GitHub CLI. Running: gh auth login" -ForegroundColor Yellow
    gh auth login
}
$GH_USER = gh api user --jq '.login' 2>$null
Write-Host "[OK] Authenticated as @$GH_USER" -ForegroundColor Green

# Check repo access
try {
    $null = gh api repos/kody-w/CommunityRAPP --jq '.name' 2>$null
    Write-Host "[OK] Repo access confirmed" -ForegroundColor Green
} catch {
    Write-Host "[X] No access to kody-w/CommunityRAPP" -ForegroundColor Red
    Write-Host "    Request contributor access from a repo maintainer." -ForegroundColor Red
    exit 1
}

# Python 3.11
function Find-Python311 {
    foreach ($cmd in @("python3.11", "python311")) {
        $fullPath = Get-Command $cmd -ErrorAction SilentlyContinue
        if ($fullPath) {
            $ver = & $fullPath.Source --version 2>&1
            if ($ver -match "Python 3\.11") { return $fullPath.Source }
        }
    }
    try { $ver = & py -3.11 --version 2>&1; if ($ver -match "Python 3\.11") { return "py -3.11" } } catch {}
    foreach ($p in @("$env:LOCALAPPDATA\Programs\Python\Python311\python.exe", "C:\Python311\python.exe")) {
        if (Test-Path $p) { $ver = & $p --version 2>&1; if ($ver -match "Python 3\.11") { return $p } }
    }
    return $null
}

$PYTHON_CMD = Find-Python311
if (-not $PYTHON_CMD) {
    Write-Host "Installing Python 3.11..." -ForegroundColor Yellow
    winget install Python.Python.3.11 --accept-source-agreements --accept-package-agreements
    $env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")
    Start-Sleep -Seconds 2
    $PYTHON_CMD = Find-Python311
    if (-not $PYTHON_CMD) { Write-Host "[X] Failed to install Python 3.11" -ForegroundColor Red; exit 1 }
}
Write-Host "[OK] Python 3.11: $PYTHON_CMD" -ForegroundColor Green

# Azure Functions Core Tools
if (-not (Get-Command func -ErrorAction SilentlyContinue)) {
    Write-Host "Installing Azure Functions Core Tools..." -ForegroundColor Yellow
    winget install Microsoft.Azure.FunctionsCoreTools --accept-source-agreements --accept-package-agreements
    $env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")
}
Write-Host "[OK] Azure Functions Core Tools" -ForegroundColor Green

# ── Clone & Setup ────────────────────────────────────────────
Write-Host ""
Write-Host "Cloning CommunityRAPP..." -ForegroundColor Yellow
if (Test-Path "CommunityRAPP") {
    Set-Location CommunityRAPP; git pull
} else {
    gh repo clone kody-w/CommunityRAPP; Set-Location CommunityRAPP
}
Write-Host "[OK] Repository cloned" -ForegroundColor Green

Write-Host "Setting up Python environment..." -ForegroundColor Yellow
if (Test-Path ".venv") { Remove-Item -Recurse -Force .venv }
if ($PYTHON_CMD -eq "py -3.11") { & py -3.11 -m venv .venv } else { & $PYTHON_CMD -m venv .venv }
.venv\Scripts\Activate.ps1
pip install --upgrade pip -q
pip install -r requirements.txt -q
Write-Host "[OK] Dependencies installed" -ForegroundColor Green

# ── Config ───────────────────────────────────────────────────
if (-not (Test-Path "local.settings.json")) {
    Write-Host ""
    Write-Host "No local.settings.json found." -ForegroundColor Yellow
    Write-Host "Two options:" -ForegroundColor White
    Write-Host "  1. Deploy to Azure first: click the Deploy button in README.md"
    Write-Host "     Then copy the setup script from the Outputs tab."
    Write-Host "  2. Copy the template and fill in your Azure values:"
    Write-Host "     cp local.settings.template.json local.settings.json"
}

# ── Done ─────────────────────────────────────────────────────
Write-Host ""
Write-Host "========================================" -ForegroundColor Green
Write-Host "  CommunityRAPP is ready!" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
Write-Host ""
Write-Host "Next steps:" -ForegroundColor White
Write-Host "  cd CommunityRAPP"
Write-Host "  .venv\Scripts\Activate.ps1"
Write-Host ""
Write-Host "  # If you have local.settings.json configured:" -ForegroundColor White
Write-Host "  func start"
Write-Host ""
Write-Host "  # If not, deploy to Azure first:" -ForegroundColor White
Write-Host "  # Click the Deploy to Azure button in README.md"
