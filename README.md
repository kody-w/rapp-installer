# 🧠 RAPP Brainstem

<!-- rapp1:network-header:start -->
[![RAPP/1](https://kody-w.github.io/rapp-hive-public/portfolio/badges/rapp-installer.svg)](https://github.com/kody-w/rapp-hive-public/blob/main/portfolio/repos/rapp-installer.md) · **New to RAPP?** [Start here: get your Brainstem →](https://github.com/kody-w/rapp-installer#start-here)
<!-- rapp1:network-header:end -->

## Start here

A local-first AI agent server powered by GitHub Copilot. No API keys. No cloud setup. Just your GitHub account.

**RAPP/1 LTS: Brainstem v0.6.9.** This is the kernel RAPP/1 is pinned to (`KERNEL_PIN.json` in [kody-w/RAPP](https://github.com/kody-w/RAPP), channel `lts`), installed from the `brainstem-v0.6.9` tag.

macOS and Linux:

```bash
curl -fsSL https://raw.githubusercontent.com/kody-w/rapp-installer/brainstem-v0.6.9/install.sh | bash -s -- --version brainstem-v0.6.9
```

Windows (PowerShell):

```powershell
irm https://raw.githubusercontent.com/kody-w/rapp-installer/brainstem-v0.6.9/install.ps1 | iex
```

> [!NOTE]
> The Windows installer can't pin a version: even at this tag it clones `main`, so it installs the current kernel, not v0.6.9.

Both install into `~/.brainstem` and add the `brainstem` command. Then run `gh auth login` once; `brainstem` starts the server at `localhost:7071`.

### Newest channel

The newest Brainstem, which moves with `main`:

> **👉 [Get Started at kody-w.github.io/rapp-installer](https://kody-w.github.io/rapp-installer/)**

```
curl -fsSL https://kody-w.github.io/rapp-installer/install.sh | bash
```

**Windows (PowerShell — works on factory Windows 11):**
```powershell
irm https://raw.githubusercontent.com/kody-w/rapp-installer/main/install.ps1 | iex
```
Auto-installs Python 3.11, Git, and GitHub CLI via winget if missing.

Then:
```bash
gh auth login   # one-time GitHub auth
brainstem       # start the server → localhost:7071
```

---

## Install Brainstem + RAR from Scout or Copilot CLI

RAPP Installer follows the same plugin-marketplace pattern used by Microsoft
Power CAT Skills:

| Plugin identity | Purpose |
|---|---|
| `rapp@brainstem` | Install and verify Brainstem, then install RAR |
| `rapp@rar` | Operate RAR, skills, exports, and callback bootstrap |

```bash
copilot plugin marketplace add kody-w/rapp-installer
copilot plugin install rapp@brainstem
```

Claude Code uses the same marketplace:

```bash
claude plugin marketplace add kody-w/rapp-installer
claude plugin install rapp@brainstem
```

Or ask Scout:

```text
Add the kody-w/rapp-installer marketplace and install
rapp@brainstem. Then install my local Brainstem and RAR.
```

The `rapp-bootstrap` skill installs and verifies Brainstem, then registers the
`kody-w/RAR` marketplace and installs `rapp@rar`. Start a new conversation
afterward so Scout or Copilot CLI discovers the RAR skill manager.

The `rapp@x` identity is governed by
[MARKETPLACE_CHARTER.md](MARKETPLACE_CHARTER.md) and RAR Constitution Article
XXV. The same manifests are also loadable by Claude Code.

---

## Or: Start with the Cloud Backend (Hippocampus)

Want persistent memory, Azure Functions, and a path to Copilot Studio? Skip the brainstem and go straight to Tier 2:

**Mac / Linux:**
```bash
curl -fsSL https://raw.githubusercontent.com/kody-w/rapp-installer/main/community_rapp/install.sh | bash
```

**Windows:**
```powershell
irm https://raw.githubusercontent.com/kody-w/rapp-installer/main/community_rapp/install.ps1 | iex
```

Creates `~/rapp-projects/my-project/` — isolated project with its own venv, agents, and local storage. Auth happens through the chat UI (GitHub device code flow). No API keys needed to start.

[Onboarding guide](https://kody-w.github.io/CommunityRAPP/onboard.html) | [CommunityRAPP repo](https://github.com/kody-w/CommunityRAPP)

---

## How It Works

The brainstem is a Flask server that connects to GitHub Copilot's API for LLM inference. You define a **soul** (system prompt) and drop in **agents** (Python tools the LLM can call). That's it.

```
~/.brainstem/src/rapp_brainstem/
├── brainstem.py       # the server
├── soul.md            # personality (system prompt)
├── agents/            # auto-discovered tools
│   └── hello_agent.py
├── local_storage.py   # local-first storage shim
└── .env               # config (model, paths, port)
```

### Write an Agent

Any `*_agent.py` file in your agents directory gets auto-discovered and registered as a tool:

```python
from basic_agent import BasicAgent

class WeatherAgent(BasicAgent):
    def __init__(self):
        self.name = "Weather"
        self.metadata = {
            "name": self.name,
            "description": "Gets the weather for a city.",
            "parameters": {
                "type": "object",
                "properties": {
                    "city": {"type": "string", "description": "City name"}
                },
                "required": ["city"]
            }
        }
        super().__init__()

    def perform(self, city="", **kwargs):
        return f"It's sunny in {city}!"
```

### Connect Remote Agent Repos

The chat UI has a **Sources** panel — paste any GitHub repo URL with an `agents/` folder and the brainstem hot-loads them. Missing pip dependencies are auto-installed.

---

## The Stack: Brainstem → Azure → Copilot Studio

RAPP teaches you the Microsoft AI stack one layer at a time. Start with the brainstem locally, then layer up when you're ready.

### 🧠 Tier 1: The Brainstem (local)

The survival basics. The brainstem runs the core agent loop — soul, tool-calling, conversation. Your GitHub Copilot subscription is the AI engine.

**What you learn:** Python agents, function-calling, prompt engineering, local-first development.

### ☁️ Tier 2: The Spinal Cord (Azure)

Give your brainstem a cloud body. Deploy to Azure so it's always-on with persistent storage, monitoring, and Azure OpenAI.

```bash
# Deploy via script
curl -fsSL https://raw.githubusercontent.com/kody-w/rapp-installer/main/deploy.sh | bash
```

Or click: [![Deploy to Azure](https://aka.ms/deploytoazurebutton)](https://portal.azure.com/#create/Microsoft.Template/uri/https%3A%2F%2Fraw.githubusercontent.com%2Fkody-w%2Frapp-installer%2Fmain%2Fazuredeploy.json)

Creates: Function App (Python 3.11), Azure OpenAI (GPT-4o), Storage Account, Application Insights. All Entra ID auth — no API keys.

**What you learn:** ARM templates, Azure Functions, managed identity, RBAC, Azure OpenAI.

### 🤖 Tier 3: The Nervous System (Copilot Studio)

Connect your agent to Teams and M365 Copilot. Import the included Power Platform solution (`MSFTAIBASMultiAgentCopilot_*.zip`) into Copilot Studio, point it at your Azure Function, and publish.

The same agent logic you tested locally now answers in Microsoft Teams and M365 Copilot across your organization.

**What you learn:** Copilot Studio, declarative agents, Power Platform solutions, Teams integration, enterprise AI.

---

## Configuration

All config via `.env` (see `.env.example`):

| Variable | Default | Description |
|----------|---------|-------------|
| `GITHUB_TOKEN` | auto-detected via `gh` | GitHub PAT or Copilot token |
| `GITHUB_MODEL` | `gpt-4o` | Model ([GitHub Models](https://github.com/marketplace/models)) |
| `SOUL_PATH` | `./soul.md` | Path to your soul file |
| `AGENTS_PATH` | `./agents` | Path to your agents directory |
| `PORT` | `7071` | Server port |

## API

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/chat` | POST | `{"user_input": "...", "conversation_history": [], "session_id": "..."}` |
| `/health` | GET | Status, model, loaded agents, token state |
| `/login` | POST | Start GitHub device code OAuth flow |
| `/models` | GET | List available models |
| `/repos` | GET | List connected agent repos |

## Requirements

- **Python 3.11+**
- **Git**
- **GitHub account** with Copilot access

## Updating

```bash
cd ~/.brainstem/src && git pull
```

## Uninstalling

```bash
rm -rf ~/.brainstem ~/.local/bin/brainstem
```
