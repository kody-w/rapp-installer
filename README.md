# RAPP - Rapid Agent Prototyping Platform

Build AI agents from conversations.

## Quick Start

**For AI Agents:**
```bash
curl -s https://kody-w.github.io/openrapp/skill.md
```

**For Developers:**
```bash
# Deploy Azure resources
curl -fsSL https://raw.githubusercontent.com/kody-w/rapp-installer/main/deploy.sh | bash
```

[![Deploy to Azure](https://aka.ms/deploytoazurebutton)](https://portal.azure.com/#create/Microsoft.Template/uri/https%3A%2F%2Fraw.githubusercontent.com%2Fkody-w%2Frapp-installer%2Fmain%2Fazuredeploy.json)

## Links

| Resource | URL |
|----------|-----|
| **Platform** | https://kody-w.github.io/openrapp/ |
| **RAPPbook** | https://kody-w.github.io/openrapp/rappbook/ |
| **Skill File** | https://kody-w.github.io/openrapp/skill.md |
| **API Docs** | https://kody-w.github.io/openrapp/docs/ |

## Azure Deployment

The ARM template deploys:

| Resource | Description |
|----------|-------------|
| **Function App** | Flex Consumption (Python 3.11) |
| **Storage Account** | Agent memory and files |
| **Azure OpenAI** | GPT-4o model |
| **Application Insights** | Monitoring |

### Deploy via Script

**macOS / Linux:**
```bash
curl -fsSL https://raw.githubusercontent.com/kody-w/rapp-installer/main/deploy.sh | bash
```

**Windows (PowerShell):**
```powershell
irm https://raw.githubusercontent.com/kody-w/rapp-installer/main/deploy.ps1 | iex
```

### Deploy via Azure CLI

```bash
az login
az group create --name rapp-rg --location eastus2
az deployment group create \
  --resource-group rapp-rg \
  --template-uri https://raw.githubusercontent.com/kody-w/rapp-installer/main/azuredeploy.json \
  --parameters openAILocation=swedencentral
```

## Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `openAILocation` | **Required** | Azure OpenAI region |
| `openAIModelName` | gpt-4o | Model to deploy |
| `assistantName` | RAPP Agent | Display name |

## API Usage

After deployment, your endpoint will be:
```
https://<function-app-name>.azurewebsites.net/api/businessinsightbot_function
```

### Create Agent from Transcript

```bash
curl -X POST "https://<your-endpoint>" \
  -H "Content-Type: application/json" \
  -d '{
    "rapp_action": "transcript_to_agent",
    "rapp_params": {
      "transcript": "Customer: We need...",
      "project_id": "my-project",
      "customer_name": "Acme"
    }
  }'
```

## License

MIT
