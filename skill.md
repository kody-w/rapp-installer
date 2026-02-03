# RAPP Agent Installer

This skill automates the complete setup of the RAPP Agent (Rapid Agent Prototyping Platform) for local development.

## What This Skill Does

1. Clones the RAPP Agent repository
2. Checks and installs prerequisites (Python 3.11, Azure Functions Core Tools)
3. Creates Azure resources (Resource Group, OpenAI, Storage Account)
4. Configures local.settings.json with all credentials
5. Installs Python dependencies
6. Starts the function and verifies it works

## Prerequisites

- Azure subscription with permissions to create resources
- GitHub Copilot CLI installed and authenticated

## Instructions for Copilot

Execute the following steps autonomously. Only pause and ask for user input when explicitly marked with ⏸️ PAUSE.

### Step 1: Clone Repository

```bash
git clone https://github.com/kody-w/m365-agents-for-python.git
cd m365-agents-for-python/RAPPagent
```

### Step 2: Check Prerequisites

Check if the following are installed. If not, provide installation commands for the user's OS:

**Python 3.11:**
```bash
python3 --version
```

If not 3.11.x, tell user:
- Mac: `brew install python@3.11`
- Windows: Download from https://www.python.org/downloads/release/python-3110/
- Linux: `sudo apt install python3.11`

**Azure Functions Core Tools v4:**
```bash
func --version
```

If not installed:
```bash
npm install -g azure-functions-core-tools@4 --unsafe-perm true
```

**Azure CLI:**
```bash
az --version
```

If not installed, direct to: https://docs.microsoft.com/cli/azure/install-azure-cli

### Step 3: ⏸️ PAUSE - Azure Authentication

Tell the user:
> "I need you to authenticate with Azure. Please run `az login` in your terminal and complete the browser authentication. Let me know when you're done."

After user confirms, verify login:
```bash
az account show --query "{subscription:name, user:user.name}" -o table
```

If user has multiple subscriptions, ask which one to use:
```bash
az account list --query "[].{Name:name, ID:id, Default:isDefault}" -o table
```

Set the selected subscription:
```bash
az account set --subscription "SUBSCRIPTION_ID"
```

### Step 4: Create Azure Resources

Generate a unique suffix for resource names:
```bash
SUFFIX=$(openssl rand -hex 4)
RESOURCE_GROUP="rapp-rg-${SUFFIX}"
LOCATION="eastus2"
```

**Create Resource Group:**
```bash
az group create --name $RESOURCE_GROUP --location $LOCATION
```

**Create Azure OpenAI (or use existing):**

Ask user: "Do you have an existing Azure OpenAI resource? (yes/no)"

If NO, create one:
```bash
OPENAI_NAME="rapp-openai-${SUFFIX}"
az cognitiveservices account create \
  --name $OPENAI_NAME \
  --resource-group $RESOURCE_GROUP \
  --kind OpenAI \
  --sku S0 \
  --location swedencentral \
  --yes

# Deploy GPT model
az cognitiveservices account deployment create \
  --name $OPENAI_NAME \
  --resource-group $RESOURCE_GROUP \
  --deployment-name "gpt-deployment" \
  --model-name "gpt-4o" \
  --model-version "2024-08-06" \
  --model-format OpenAI \
  --sku-name "Standard" \
  --sku-capacity 10
```

Get endpoint:
```bash
OPENAI_ENDPOINT=$(az cognitiveservices account show \
  --name $OPENAI_NAME \
  --resource-group $RESOURCE_GROUP \
  --query "properties.endpoint" -o tsv)
```

If YES, ask for:
- OpenAI endpoint URL
- Deployment name

**Create Storage Account:**
```bash
STORAGE_NAME="rappst${SUFFIX}"
az storage account create \
  --name $STORAGE_NAME \
  --resource-group $RESOURCE_GROUP \
  --location $LOCATION \
  --sku Standard_LRS \
  --kind StorageV2 \
  --allow-shared-key-access false

# Create file share
az storage share-rm create \
  --name "agents" \
  --storage-account $STORAGE_NAME \
  --resource-group $RESOURCE_GROUP \
  --quota 5
```

**Assign RBAC roles to current user:**
```bash
USER_ID=$(az ad signed-in-user show --query id -o tsv)
SUBSCRIPTION_ID=$(az account show --query id -o tsv)

# Storage Blob Data Contributor
az role assignment create \
  --assignee $USER_ID \
  --role "Storage Blob Data Contributor" \
  --scope "/subscriptions/${SUBSCRIPTION_ID}/resourceGroups/${RESOURCE_GROUP}/providers/Microsoft.Storage/storageAccounts/${STORAGE_NAME}"

# Storage File Data Privileged Contributor
az role assignment create \
  --assignee $USER_ID \
  --role "Storage File Data Privileged Contributor" \
  --scope "/subscriptions/${SUBSCRIPTION_ID}/resourceGroups/${RESOURCE_GROUP}/providers/Microsoft.Storage/storageAccounts/${STORAGE_NAME}"

# Cognitive Services OpenAI User
az role assignment create \
  --assignee $USER_ID \
  --role "Cognitive Services OpenAI User" \
  --scope "/subscriptions/${SUBSCRIPTION_ID}/resourceGroups/${RESOURCE_GROUP}/providers/Microsoft.CognitiveServices/accounts/${OPENAI_NAME}"
```

### Step 5: Configure local.settings.json

Create the configuration file:
```bash
cat > local.settings.json << EOF
{
  "IsEncrypted": false,
  "Values": {
    "FUNCTIONS_WORKER_RUNTIME": "python",
    "AzureWebJobsStorage__accountName": "${STORAGE_NAME}",
    "AZURE_OPENAI_ENDPOINT": "${OPENAI_ENDPOINT}",
    "AZURE_OPENAI_API_VERSION": "2025-01-01-preview",
    "AZURE_OPENAI_DEPLOYMENT_NAME": "gpt-deployment",
    "AZURE_STORAGE_ACCOUNT_NAME": "${STORAGE_NAME}",
    "AZURE_FILES_SHARE_NAME": "agents",
    "ASSISTANT_NAME": "RAPP Agent",
    "CHARACTERISTIC_DESCRIPTION": "Rapid Agent Prototyping Platform assistant"
  }
}
EOF
```

### Step 6: Install Dependencies

```bash
pip install -r requirements.txt
```

### Step 7: Start and Test

Start the function:
```bash
func start
```

Wait for it to initialize (look for "Worker process started and initialized"), then test in a new terminal:
```bash
curl -X POST http://localhost:7071/api/businessinsightbot_function \
  -H "Content-Type: application/json" \
  -d '{"user_input": "Hello", "conversation_history": []}'
```

Expected response contains `"assistant_response"` with a greeting.

### Step 8: Success Message

Tell the user:

---

✅ **RAPP Agent is ready!**

**Local endpoint:** http://localhost:7071/api/businessinsightbot_function

**Web UI:** Open `index.html` in your browser

**Azure Resources Created:**
- Resource Group: `{RESOURCE_GROUP}`
- Storage Account: `{STORAGE_NAME}`
- OpenAI Service: `{OPENAI_NAME}`

**Next steps:**
1. Add custom agents in `agents/` folder
2. See `CLAUDE.md` for architecture details
3. Import `MSFTAIBASMultiAgentCopilot_*.zip` to Power Platform for Teams/M365 Copilot integration

---

## Cleanup (Optional)

To delete all created Azure resources:
```bash
az group delete --name $RESOURCE_GROUP --yes --no-wait
```

## Troubleshooting

| Issue | Solution |
|-------|----------|
| `az login` token expired | Run `az login` again |
| Storage auth fails | Wait 1-2 min for RBAC to propagate, then restart `func start` |
| OpenAI deployment fails | Try a different region (e.g., `eastus2` instead of `swedencentral`) |
| Python version mismatch | Ensure Python 3.11 is used, not 3.13+ |
