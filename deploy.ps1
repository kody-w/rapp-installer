# RAPP Azure Deployment Script for Windows
# Deploy Azure resources needed for RAPP
#
# Usage:
#   irm https://raw.githubusercontent.com/kody-w/rapp-installer/main/deploy.ps1 | iex
#   Or: .\deploy.ps1 [-ResourceGroup "rapp-rg"] [-Location "eastus2"] [-OpenAILocation "eastus2"]

param(
    [string]$ResourceGroup = "",
    [string]$Location = "",
    [string]$OpenAILocation = ""
)

$ErrorActionPreference = "Stop"

$TemplateUrl = "https://raw.githubusercontent.com/kody-w/rapp-installer/main/azuredeploy.json"

Write-Host ""
Write-Host "RAPP Azure Deployment" -ForegroundColor Cyan
Write-Host "======================" -ForegroundColor Cyan
Write-Host ""

# Check Azure CLI
try {
    $null = az --version 2>&1
} catch {
    Write-Host "Error: Azure CLI not found" -ForegroundColor Red
    Write-Host "Install from: https://aka.ms/installazurecli"
    exit 1
}

# Check Azure login
try {
    $account = az account show 2>&1 | ConvertFrom-Json
    if (-not $account) { throw "Not logged in" }
    Write-Host "Logged in to: $($account.name)" -ForegroundColor Green
} catch {
    Write-Host "Not logged into Azure. Running 'az login'..." -ForegroundColor Yellow
    az login
    $account = az account show | ConvertFrom-Json
    Write-Host "Logged in to: $($account.name)" -ForegroundColor Green
}

Write-Host ""

# Get parameters
if (-not $ResourceGroup) {
    $ResourceGroup = Read-Host "Resource group name [rapp-rg]"
    if (-not $ResourceGroup) { $ResourceGroup = "rapp-rg" }
}

if (-not $Location) {
    $Location = Read-Host "Azure region [eastus2]"
    if (-not $Location) { $Location = "eastus2" }
}

if (-not $OpenAILocation) {
    Write-Host ""
    Write-Host "Available Azure OpenAI regions:" -ForegroundColor Yellow
    Write-Host "  australiaeast, canadaeast, eastus, eastus2, francecentral,"
    Write-Host "  japaneast, northcentralus, norwayeast, southcentralus,"
    Write-Host "  eastus2, switzerlandnorth, uksouth, westeurope, westus, westus3"
    Write-Host ""
    $OpenAILocation = Read-Host "Azure OpenAI region [eastus2]"
    if (-not $OpenAILocation) { $OpenAILocation = "eastus2" }
}

Write-Host ""
Write-Host "Deployment Configuration:" -ForegroundColor Yellow
Write-Host "  Resource Group:  $ResourceGroup"
Write-Host "  Location:        $Location"
Write-Host "  OpenAI Location: $OpenAILocation"
Write-Host ""

$confirm = Read-Host "Proceed with deployment? (y/n) [y]"
if (-not $confirm) { $confirm = "y" }

if ($confirm -notin @("y", "Y")) {
    Write-Host "Deployment cancelled."
    exit 0
}

# Create resource group
Write-Host ""
Write-Host "Creating resource group..." -ForegroundColor Yellow
az group create --name $ResourceGroup --location $Location --output none
Write-Host "Resource group created" -ForegroundColor Green

# Deploy ARM template
Write-Host ""
Write-Host "Deploying Azure resources (this may take 5-10 minutes)..." -ForegroundColor Yellow
Write-Host "  - Function App (Flex Consumption)"
Write-Host "  - Storage Account"
Write-Host "  - Azure OpenAI Service"
Write-Host "  - Application Insights"
Write-Host ""

$deploymentOutput = az deployment group create `
    --resource-group $ResourceGroup `
    --template-uri $TemplateUrl `
    --parameters openAILocation=$OpenAILocation `
    --query "properties.outputs" `
    --output json | ConvertFrom-Json

Write-Host "Deployment complete!" -ForegroundColor Green
Write-Host ""

# Extract outputs
$functionAppName = $deploymentOutput.functionAppName.value
$functionUrl = $deploymentOutput.functionEndpoint.value
$storageAccount = $deploymentOutput.storageAccountName.value
$openAIEndpoint = $deploymentOutput.openAIEndpoint.value

Write-Host "===================================================" -ForegroundColor Cyan
Write-Host "  RAPP Azure Resources Deployed!" -ForegroundColor Green
Write-Host "===================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "  Resource Group:    $ResourceGroup"
Write-Host "  Function App:      $functionAppName"
Write-Host "  Storage Account:   $storageAccount"
Write-Host "  OpenAI Endpoint:   $openAIEndpoint"
Write-Host ""
Write-Host "  Function URL:"
Write-Host "  $functionUrl"
Write-Host ""
Write-Host "===================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Next steps:"
Write-Host "  1. Install RAPP:"
Write-Host "     irm https://raw.githubusercontent.com/kody-w/rapp-installer/main/install.ps1 | iex"
Write-Host ""
Write-Host "  2. Run setup and select 'existing' to connect:"
Write-Host "     rapp setup"
Write-Host ""
Write-Host "  3. Or deploy code to your Function App:"
Write-Host "     func azure functionapp publish $functionAppName --build remote"
Write-Host ""

# Save outputs to file
$outputFile = "rapp-deployment-outputs.json"
$deploymentOutput | ConvertTo-Json -Depth 10 | Set-Content -Path $outputFile
Write-Host "Full deployment outputs saved to: $outputFile"
