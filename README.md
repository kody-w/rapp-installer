# RAPP - Rapid AI Agent Production Pipeline

Build production-ready AI agents from transcripts in minutes.

**New to RAPP?** Check out our [Getting Started Guide](https://kody-w.github.io/rapp-installer/) for a visual walkthrough.

## RAPP Ecosystem

```
┌─────────────────────────────────────────────────────────────────┐
│                      RAPP ECOSYSTEM                              │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐ │
│  │  RAPP Installer │  │    RAPP Hub     │  │   RAPP Store    │ │
│  │   (This Repo)   │  │ (Implementations)│  │ (Agents/Skills) │ │
│  │                 │  │                 │  │                 │ │
│  │ • Install RAPP  │  │ • Browse apps   │  │ • Browse agents │ │
│  │ • Deploy Azure  │  │ • Clone & run   │  │ • Download code │ │
│  │ • Setup env     │  │ • Publish yours │  │ • Cross-format  │ │
│  └────────┬────────┘  └────────┬────────┘  └────────┬────────┘ │
│           │                    │                    │           │
│           └────────────────────┼────────────────────┘           │
│                                │                                │
│                    ┌───────────▼───────────┐                   │
│                    │   Your AI Project     │                   │
│                    │   (rapp.json deps)    │                   │
│                    └───────────────────────┘                   │
└─────────────────────────────────────────────────────────────────┘
```

| Component | Description | Link |
|-----------|-------------|------|
| **RAPP Desktop** | Native desktop application | [kody-w/RAPP_Desktop](https://github.com/kody-w/RAPP_Desktop) |
| **RAPP Installer** | Bootstrapper & Azure deployment | [This repo](https://github.com/kody-w/rapp-installer) |
| **RAPP Hub** | Implementation registry | [kody-w/RAPP_Hub](https://github.com/kody-w/RAPP_Hub) |
| **RAPP Store** | Agent & skill packages | [kody-w/RAPP_Store](https://github.com/kody-w/RAPP_Store) |

### Quick Links
- **Desktop App**: https://github.com/kody-w/RAPP_Desktop/releases
- **Browse Implementations**: https://kody-w.github.io/RAPP_Hub/
- **Browse Agents/Skills**: https://kody-w.github.io/RAPP_Store/

[![Deploy to Azure](https://aka.ms/deploytoazurebutton)](https://portal.azure.com/#create/Microsoft.Template/uri/https%3A%2F%2Fraw.githubusercontent.com%2Fkody-w%2Frapp-installer%2Fmain%2Fazuredeploy.json)

## Install via GitHub Copilot CLI (Recommended)

If you have GitHub Copilot CLI installed, use the included skill for guided installation:

```bash
gh copilot skill https://raw.githubusercontent.com/kody-w/rapp-installer/main/skill.md
```

### What It Does

- Clones the RAPP Agent repository
- Creates Azure resources (OpenAI, Storage Account)
- Configures authentication and local settings
- Starts the function locally

### Requirements

- GitHub Copilot CLI
- Azure subscription
- Node.js (for Azure Functions Core Tools)
- **GitHub contributor access** to [kody-w/RAPPagent](https://github.com/kody-w/RAPPagent) (private repo - request access from owner)

---

## Install via Script

**macOS / Linux:**
```bash
curl -fsSL https://raw.githubusercontent.com/kody-w/rapp-installer/main/install.sh | bash
```

**Windows (PowerShell):**
```powershell
irm https://raw.githubusercontent.com/kody-w/rapp-installer/main/install.ps1 | iex
```

**Windows (CMD):**
```cmd
curl -o install.cmd https://raw.githubusercontent.com/kody-w/rapp-installer/main/install.cmd && install.cmd
```

## After Installation

```bash
# Start RAPP (opens web UI at localhost:5050)
rapp

# Configure Azure connection
rapp setup

# Show all commands
rapp --help

# Check installation status
rapp status
```

## Requirements

- **Python 3.11+** - [Download](https://python.org)
- **Git** - [Download](https://git-scm.com)
- **GitHub account** with access to RAPP repository
- **Azure subscription** (for deployment)

### Optional

- **Azure CLI** - [Download](https://aka.ms/installazurecli) (required for `rapp setup`)
- **GitHub CLI** - [Download](https://cli.github.com) (simplifies authentication)

## Azure Deployment

RAPP requires Azure resources to run. You can deploy them using the included ARM template.

### Quick Deploy (Azure Portal)

[![Deploy to Azure](https://aka.ms/deploytoazurebutton)](https://portal.azure.com/#create/Microsoft.Template/uri/https%3A%2F%2Fraw.githubusercontent.com%2Fkody-w%2Frapp-installer%2Fmain%2Fazuredeploy.json)

### Deploy via Script (Recommended)

**macOS / Linux:**
```bash
curl -fsSL https://raw.githubusercontent.com/kody-w/rapp-installer/main/deploy.sh | bash
```

**Windows (PowerShell):**
```powershell
irm https://raw.githubusercontent.com/kody-w/rapp-installer/main/deploy.ps1 | iex
```

The script will prompt for resource group name, location, and OpenAI region.

### Deploy via Azure CLI

```bash
# Login to Azure
az login

# Create resource group
az group create --name rapp-rg --location eastus2

# Deploy resources (will prompt for OpenAI region)
az deployment group create \
  --resource-group rapp-rg \
  --template-uri https://raw.githubusercontent.com/kody-w/rapp-installer/main/azuredeploy.json \
  --parameters openAILocation=swedencentral
```

### Deploy via RAPP CLI

After installing RAPP:
```bash
rapp deploy --name rapp-rg --location eastus2
```

### What Gets Deployed

The ARM template creates:

| Resource | Description |
|----------|-------------|
| **Function App** | Flex Consumption plan (Python 3.11) |
| **Storage Account** | For agent memory and file storage |
| **Azure OpenAI** | GPT-4o model deployment |
| **Application Insights** | Monitoring and logging |

All resources use **Entra ID (Azure AD) authentication** - no API keys required.

### Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `functionAppName` | Auto-generated | Name of the Function App |
| `storageAccountName` | Auto-generated | Storage account name |
| `openAILocation` | **Required** | Region for Azure OpenAI (e.g., swedencentral, eastus2) |
| `openAIModelName` | gpt-4o | Model to deploy (gpt-4o, gpt-4o-mini, o1, o3-mini) |
| `openAIDeploymentCapacity` | 10 | Tokens per minute (thousands) |
| `assistantName` | RAPP Agent | Display name for the assistant |

### Post-Deployment

After deployment completes:

1. Get the Function App URL from the deployment outputs
2. Run `rapp setup` and select "existing" to connect to your deployed resources
3. Or manually create `local.settings.json` using the template from deployment outputs

## Access

RAPP is currently in private beta. The installation script will prompt for GitHub authentication to access the private repository.

To request access, contact the repository owner.

## What Gets Installed

The installer:
1. Verifies prerequisites (Python 3.11+, Git)
2. Prompts for GitHub authentication
3. Clones the RAPP source code to `~/.rapp/src`
4. Creates a Python virtual environment at `~/.rapp/venv`
5. Installs dependencies
6. Adds the `rapp` command to your PATH

### Installation Directory

```
~/.rapp/
├── config.json          # Your configuration
├── venv/                # Python virtual environment
└── src/                 # RAPP source code
    ├── rapp_pipeline/   # Web UI
    ├── rapp_ai/         # Azure Functions + agents
    ├── rapp_cli/        # CLI module
    └── ...
```

## Troubleshooting

### "Python 3.11+ required"

Install Python 3.11 or later from [python.org](https://python.org).

On macOS with Homebrew:
```bash
brew install python@3.11
```

### "Failed to clone repository"

You need access to the private RAPP repository. Either:
1. Request access from the repository owner
2. Ensure you're authenticated with GitHub (use `gh auth login` or configure git credentials)

### Command not found: rapp

After installation, restart your terminal or run:
```bash
source ~/.bashrc  # or ~/.zshrc
```

On Windows, open a new terminal window.

### Azure CLI not found

Install the Azure CLI from [aka.ms/installazurecli](https://aka.ms/installazurecli).

This is only required for `rapp setup` to configure Azure resources.

## Updating

To update RAPP to the latest version:
```bash
rapp update
```

## Uninstalling

To remove RAPP:
```bash
rm -rf ~/.rapp
rm ~/.local/bin/rapp
```

On Windows:
```powershell
Remove-Item -Recurse -Force "$env:USERPROFILE\.rapp"
Remove-Item "$env:USERPROFILE\.local\bin\rapp.cmd"
```
