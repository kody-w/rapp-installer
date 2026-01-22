#!/bin/bash
# RAPP Azure Deployment Script
# Deploy Azure resources needed for RAPP
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/kody-w/rapp-installer/main/deploy.sh | bash
#   Or: ./deploy.sh [resource-group-name] [location] [openai-location]

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

TEMPLATE_URL="https://raw.githubusercontent.com/kody-w/rapp-installer/main/azuredeploy.json"

echo ""
echo -e "${CYAN}RAPP Azure Deployment${NC}"
echo "======================"
echo ""

# Check Azure CLI
if ! command -v az &> /dev/null; then
    echo -e "${RED}Error: Azure CLI not found${NC}"
    echo "Install from: https://aka.ms/installazurecli"
    exit 1
fi

# Check Azure login
if ! az account show &> /dev/null 2>&1; then
    echo -e "${YELLOW}Not logged into Azure. Running 'az login'...${NC}"
    az login
fi

ACCOUNT=$(az account show --query name -o tsv)
echo -e "${GREEN}Logged in to: $ACCOUNT${NC}"
echo ""

# Get parameters
RESOURCE_GROUP="${1:-}"
LOCATION="${2:-}"
OPENAI_LOCATION="${3:-}"

if [ -z "$RESOURCE_GROUP" ]; then
    read -p "Resource group name [rapp-rg]: " RESOURCE_GROUP
    RESOURCE_GROUP="${RESOURCE_GROUP:-rapp-rg}"
fi

if [ -z "$LOCATION" ]; then
    read -p "Azure region [eastus2]: " LOCATION
    LOCATION="${LOCATION:-eastus2}"
fi

if [ -z "$OPENAI_LOCATION" ]; then
    echo ""
    echo "Available Azure OpenAI regions:"
    echo "  australiaeast, canadaeast, eastus, eastus2, francecentral,"
    echo "  japaneast, northcentralus, norwayeast, southcentralus,"
    echo "  swedencentral, switzerlandnorth, uksouth, westeurope, westus, westus3"
    echo ""
    read -p "Azure OpenAI region [swedencentral]: " OPENAI_LOCATION
    OPENAI_LOCATION="${OPENAI_LOCATION:-swedencentral}"
fi

echo ""
echo -e "${YELLOW}Deployment Configuration:${NC}"
echo "  Resource Group:  $RESOURCE_GROUP"
echo "  Location:        $LOCATION"
echo "  OpenAI Location: $OPENAI_LOCATION"
echo ""

read -p "Proceed with deployment? (y/n) [y]: " CONFIRM
CONFIRM="${CONFIRM:-y}"

if [[ "$CONFIRM" != "y" && "$CONFIRM" != "Y" ]]; then
    echo "Deployment cancelled."
    exit 0
fi

# Create resource group
echo ""
echo -e "${YELLOW}Creating resource group...${NC}"
az group create --name "$RESOURCE_GROUP" --location "$LOCATION" --output none
echo -e "${GREEN}Resource group created${NC}"

# Deploy ARM template
echo ""
echo -e "${YELLOW}Deploying Azure resources (this may take 5-10 minutes)...${NC}"
echo "  - Function App (Flex Consumption)"
echo "  - Storage Account"
echo "  - Azure OpenAI Service"
echo "  - Application Insights"
echo ""

DEPLOYMENT_OUTPUT=$(az deployment group create \
    --resource-group "$RESOURCE_GROUP" \
    --template-uri "$TEMPLATE_URL" \
    --parameters openAILocation="$OPENAI_LOCATION" \
    --query "properties.outputs" \
    --output json)

echo -e "${GREEN}Deployment complete!${NC}"
echo ""

# Extract outputs
FUNCTION_APP=$(echo "$DEPLOYMENT_OUTPUT" | grep -o '"functionAppName":{"type":"String","value":"[^"]*"' | cut -d'"' -f8)
FUNCTION_URL=$(echo "$DEPLOYMENT_OUTPUT" | grep -o '"functionEndpoint":{"type":"String","value":"[^"]*"' | cut -d'"' -f8)
STORAGE_ACCOUNT=$(echo "$DEPLOYMENT_OUTPUT" | grep -o '"storageAccountName":{"type":"String","value":"[^"]*"' | cut -d'"' -f8)
OPENAI_ENDPOINT=$(echo "$DEPLOYMENT_OUTPUT" | grep -o '"openAIEndpoint":{"type":"String","value":"[^"]*"' | cut -d'"' -f8)

echo "═══════════════════════════════════════════════════"
echo -e "  ${GREEN}RAPP Azure Resources Deployed!${NC}"
echo "═══════════════════════════════════════════════════"
echo ""
echo "  Resource Group:    $RESOURCE_GROUP"
echo "  Function App:      $FUNCTION_APP"
echo "  Storage Account:   $STORAGE_ACCOUNT"
echo "  OpenAI Endpoint:   $OPENAI_ENDPOINT"
echo ""
echo "  Function URL:"
echo "  $FUNCTION_URL"
echo ""
echo "═══════════════════════════════════════════════════"
echo ""
echo "Next steps:"
echo "  1. Install RAPP:"
echo "     curl -fsSL https://raw.githubusercontent.com/kody-w/rapp-installer/main/install.sh | bash"
echo ""
echo "  2. Run setup and select 'existing' to connect:"
echo "     rapp setup"
echo ""
echo "  3. Or deploy code to your Function App:"
echo "     func azure functionapp publish $FUNCTION_APP --build remote"
echo ""

# Save outputs to file
OUTPUT_FILE="rapp-deployment-outputs.json"
echo "$DEPLOYMENT_OUTPUT" > "$OUTPUT_FILE"
echo "Full deployment outputs saved to: $OUTPUT_FILE"
