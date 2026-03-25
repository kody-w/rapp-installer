"""
Onboarding — Guides users through the RAPP Brainstem journey.

Interactive guide from first launch through all three tiers:
  Tier 1 (Brainstem)      — local Flask server, writing agents, soul file
  Tier 2 (Spinal Cord)    — Azure deployment, cloud services
  Tier 3 (Nervous System) — Copilot Studio, M365/Teams integration

Actions:
  start       — detect where the user is and suggest next steps
  tier1       — Tier 1 guide: local setup, first agent, soul file
  tier2       — Tier 2 guide: Azure deployment
  tier3       — Tier 3 guide: Copilot Studio deployment
  build-agent — walkthrough: create a custom agent from scratch
  checklist   — show progress checklist across all tiers

Follows the Single File Agent pattern (Constitution Article IV).
"""

import json
import os
import subprocess
from pathlib import Path

from agents.basic_agent import BasicAgent


def _detect_tier(project_root: Path) -> dict:
    """Detect which tier the user is at based on what exists."""
    checks = {
        # Tier 1 — Local
        "brainstem_running": False,
        "soul_file": (project_root / "soul.md").exists(),
        "agents_dir": (project_root / "agents").exists(),
        "custom_agents": [],
        "env_file": (project_root / ".env").exists(),
        "memory_data": (project_root / ".brainstem_data").exists(),

        # Tier 2 — Azure
        "azure_deploy": (project_root / "azuredeploy.json").exists(),
        "azure_configured": False,

        # Tier 3 — Copilot Studio
        "copilot_studio_workspace": (project_root / "copilot-studio").exists(),
        "copilot_studio_connected": False,
        "copilot_studio_agent": (project_root / "agents" / "copilot_studio_agent.py").exists(),
        "deploy_script": (project_root / "deploy.sh").exists(),
    }

    # Check if brainstem is running
    try:
        import urllib.request
        urllib.request.urlopen("http://localhost:7071/health", timeout=2)
        checks["brainstem_running"] = True
    except Exception:
        pass

    # Count custom agents
    agents_dir = project_root / "agents"
    builtin = {"basic_agent.py", "context_memory_agent.py", "manage_memory_agent.py",
               "hacker_news_agent.py", "copilot_studio_agent.py", "onboarding_agent.py"}
    if agents_dir.exists():
        for f in agents_dir.glob("*_agent.py"):
            if f.name not in builtin:
                checks["custom_agents"].append(f.name)

    # Check Azure config
    if checks["env_file"]:
        env_content = (project_root / ".env").read_text(encoding="utf-8")
        checks["azure_configured"] = "AZURE" in env_content.upper()

    # Check Copilot Studio connection
    conn_path = project_root / "copilot-studio" / "RAPP Brainstem" / ".mcs" / "conn.json"
    checks["copilot_studio_connected"] = conn_path.exists()

    # Determine current tier
    if checks["copilot_studio_connected"]:
        tier = 3
    elif checks["azure_configured"]:
        tier = 2
    else:
        tier = 1

    checks["current_tier"] = tier
    return checks


class OnboardingAgent(BasicAgent):
    def __init__(self):
        self.name = "Onboarding"
        self.metadata = {
            "name": self.name,
            "description": (
                "Guides users through the RAPP Brainstem journey from local "
                "setup through Azure deployment to Copilot Studio. Detects "
                "where you are and suggests next steps. Ask about any tier."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "description": "What to show.",
                        "enum": ["start", "tier1", "tier2", "tier3",
                                 "build-agent", "checklist"]
                    }
                },
                "required": []
            }
        }
        super().__init__(name=self.name, metadata=self.metadata)

    def perform(self, **kwargs):
        action = kwargs.get("action", "start")
        project_root = Path(__file__).resolve().parent.parent
        checks = _detect_tier(project_root)

        handlers = {
            "start": self._start,
            "tier1": self._tier1,
            "tier2": self._tier2,
            "tier3": self._tier3,
            "build-agent": self._build_agent,
            "checklist": self._checklist,
        }
        handler = handlers.get(action, self._start)
        return handler(checks, project_root)

    def _start(self, checks: dict, project_root: Path) -> str:
        tier = checks["current_tier"]
        lines = [
            "# Welcome to RAPP Brainstem",
            "",
            f"You're currently at **Tier {tier}**.",
            "",
        ]

        if tier == 1:
            lines += self._tier1_status(checks)
            if not checks["brainstem_running"]:
                lines += [
                    "## Get Started",
                    "",
                    "Start the brainstem:",
                    "```bash",
                    "./start.sh",
                    "# or: python brainstem.py",
                    "```",
                    "",
                ]
            lines += [
                "## What's Next?",
                "",
                "- **Write your first agent** — ask me with action='build-agent'",
                "- **Customize your soul** — edit `soul.md` to change the AI's personality",
                "- **Check your progress** — ask me with action='checklist'",
                "- **When you're ready to scale** — ask about Tier 2 (Azure) or Tier 3 (Copilot Studio)",
            ]
        elif tier == 2:
            lines += [
                "You've configured Azure. Nice.",
                "",
                "## What's Next?",
                "",
                "- **Deploy to Azure** — `az deployment group create` with `azuredeploy.json`",
                "- **Move to Tier 3** — ask me with action='tier3' to reach M365/Teams",
                "- **Check your progress** — ask me with action='checklist'",
            ]
        elif tier == 3:
            lines += [
                "You're connected to Copilot Studio. Full nervous system online.",
                "",
                "## What's Next?",
                "",
                "- **Deploy** — say 'deploy to Copilot Studio' (calls the CopilotStudio agent)",
                "- **Test** — try SaveMemory and RecallMemory in the Copilot Studio test panel",
                "- **Check your progress** — ask me with action='checklist'",
            ]

        return "\n".join(lines)

    def _tier1(self, checks: dict, project_root: Path) -> str:
        lines = [
            "# Tier 1 — The Brainstem",
            "",
            "Local-first AI agent server. No cloud needed.",
            "",
            "## Architecture",
            "",
            "```",
            "brainstem.py (Flask server, port 7071)",
            "  |-- soul.md (system prompt / personality)",
            "  |-- agents/*_agent.py (auto-discovered tools)",
            "  |-- .env (config: model, port, token)",
            "  |-- local_storage.py (JSON-based memory)",
            "```",
            "",
            "## Setup Steps",
            "",
            "1. **Install** — one-liner: `curl -fsSL https://kody-w.github.io/rapp-installer/install.sh | bash`",
            "2. **Start** — `./start.sh` or `python brainstem.py`",
            "3. **Open** — http://localhost:7071 in your browser",
            "4. **Chat** — the AI loads `soul.md` and discovers all agents automatically",
            "",
            "## Authentication",
            "",
            "Uses your GitHub account with Copilot access. Three ways:",
            "- `GITHUB_TOKEN` in `.env`",
            "- Device code login (web UI shows the code)",
            "- `gh auth login` (GitHub CLI)",
            "",
            "## Your First Agent",
            "",
            "Ask me with action='build-agent' for a step-by-step walkthrough.",
            "",
            "## Built-in Agents",
            "",
            "| Agent | What It Does |",
            "|-------|-------------|",
            "| ContextMemory | Recalls stored memories from past conversations |",
            "| ManageMemory | Saves facts, preferences, insights to persistent storage |",
            "| HackerNews | Fetches top 10 stories from Hacker News API |",
            "| CopilotStudio | Deploys to Copilot Studio (Tier 3) |",
            "| Onboarding | This guide |",
            "",
        ]
        lines += self._tier1_status(checks)
        return "\n".join(lines)

    def _tier1_status(self, checks: dict) -> list[str]:
        r = "running" if checks["brainstem_running"] else "not running"
        s = "exists" if checks["soul_file"] else "missing"
        e = "exists" if checks["env_file"] else "missing (using defaults)"
        m = "has data" if checks["memory_data"] else "empty"
        c = checks["custom_agents"]
        return [
            "## Current Status",
            "",
            f"- Server: **{r}**",
            f"- Soul file: **{s}**",
            f"- .env: **{e}**",
            f"- Memory: **{m}**",
            f"- Custom agents: **{len(c)}** {('(' + ', '.join(c) + ')') if c else ''}",
            "",
        ]

    def _tier2(self, checks: dict, project_root: Path) -> str:
        has_arm = checks["azure_deploy"]
        return "\n".join([
            "# Tier 2 — The Spinal Cord",
            "",
            "Deploy your brainstem to Azure. Same agents, cloud scale.",
            "",
            "## What Changes",
            "",
            "| Local (Tier 1) | Azure (Tier 2) |",
            "|----------------|----------------|",
            "| Flask on localhost | Azure Functions |",
            "| GitHub Copilot API | Azure OpenAI |",
            "| JSON file storage | Azure File Share |",
            "| Manual start | Always-on cloud service |",
            "| Single user | Multi-user with auth |",
            "",
            "## Prerequisites",
            "",
            "- Azure subscription",
            "- Azure CLI (`az login`)",
            "- A working Tier 1 brainstem with agents you want to deploy",
            "",
            "## Deployment Steps",
            "",
            "1. **Configure** — set Azure variables in `.env`:",
            "   ```",
            "   AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com",
            "   AZURE_OPENAI_KEY=your-key",
            "   AZURE_STORAGE_CONNECTION_STRING=your-connection-string",
            "   ```",
            "",
            "2. **Deploy** — use the ARM template:" if has_arm else "2. **Deploy** — ARM template not found, create `azuredeploy.json`",
            "   ```bash",
            "   az deployment group create \\",
            "     --resource-group your-rg \\",
            "     --template-file azuredeploy.json",
            "   ```",
            "",
            "3. **Verify** — check the Function App health endpoint",
            "",
            "4. **Migrate agents** — your `*_agent.py` files work unchanged.",
            "   The Azure deployment uses the same `BasicAgent` pattern.",
            "   Storage switches from `local_storage.py` to Azure File Share automatically.",
            "",
            "## What Stays the Same",
            "",
            "- Same agent pattern (one file, one agent)",
            "- Same soul.md personality",
            "- Same memory format (JSON, now on Azure File Share)",
            "- Same API contract (/chat, /health, /agents)",
            "",
            f"ARM template: **{'found' if has_arm else 'not found'}**",
            "",
            "When you're ready for M365/Teams, ask about Tier 3.",
        ])

    def _tier3(self, checks: dict, project_root: Path) -> str:
        connected = checks["copilot_studio_connected"]
        has_agent = checks["copilot_studio_agent"]
        has_deploy = checks["deploy_script"]
        return "\n".join([
            "# Tier 3 — The Nervous System",
            "",
            "Publish to Copilot Studio. Your brainstem reaches into M365, Teams, and the enterprise.",
            "",
            "## What Changes",
            "",
            "| Local/Azure (Tier 1-2) | Copilot Studio (Tier 3) |",
            "|------------------------|------------------------|",
            "| Python agents | YAML topics + Power Automate flows |",
            "| JSON file storage | OOTB Dataverse Notes table |",
            "| Flask/Functions API | Copilot Studio generative AI |",
            "| Browser UI | Teams, M365 Copilot |",
            "",
            "## How It Works",
            "",
            "The CopilotStudio agent (`copilot_studio_agent.py`) handles everything:",
            "",
            "1. **Scans** your Python agents and classifies them",
            "2. **Generates** Copilot Studio YAML with battle-tested templates",
            "3. **Pushes** to the cloud (push = publish, no separate step)",
            "4. **Auto-detects** Power Automate flow GUIDs from your workspace",
            "",
            "## Getting Started",
            "",
            "1. **Clone an agent from Copilot Studio** (one-time setup):",
            "   - Open [copilotstudio.microsoft.com](https://copilotstudio.microsoft.com)",
            "   - Create a new agent or use an existing one",
            "   - Use the VS Code extension to clone it locally",
            "   - This creates the `.mcs/conn.json` connection file",
            "",
            "2. **Deploy** — just say it:",
            "   ```",
            "   > Deploy to Copilot Studio",
            "   ```",
            "   Or use the deploy script: `./deploy.sh`",
            "",
            "3. **Create the Power Automate flows** (one-time, in the portal):",
            "   - SaveMemory flow → Dataverse 'Add Row' to Notes (annotations)",
            "   - RecallMemory flow → Dataverse 'List Rows' from Notes",
            "   - Pull to sync flow GUIDs, then deploy again to wire them",
            "",
            "4. **Publish** from the Copilot Studio portal (first time only)",
            "   After that, pushes auto-publish via `publishOnImport: true`",
            "",
            "## OOTB Dataverse Storage",
            "",
            "No custom tables. Memories use the built-in Notes (annotation) table:",
            "",
            "| Note Column | Maps To |",
            "|-------------|---------|",
            "| subject | memory type (rapp:fact, rapp:preference, etc.) |",
            "| notetext | memory content with importance prefix |",
            "| createdon | automatic timestamp |",
            "| _createdby | automatic user scoping |",
            "",
            "Filter: `contains(subject,'rapp:')` isolates RAPP memories from other notes.",
            "",
            "## Current Status",
            "",
            f"- CopilotStudio agent: **{'installed' if has_agent else 'not found'}**",
            f"- Workspace connected: **{'yes' if connected else 'no — clone an agent first'}**",
            f"- Deploy script: **{'ready' if has_deploy else 'not found'}**",
            "",
            "## Key Lessons (so you don't hit the same walls)",
            "",
            "- ALL topic inputs must be `StringPrebuiltEntity` (not Number/Boolean)",
            "- ALL flow bindings need `Coalesce()` with non-null defaults",
            "- `inputType`/`outputType` blocks are required for `Topic.*` Power Fx variables",
            "- Flow inputs use generic keys (`text`, `text_1`, `text_2`), not friendly names",
            "- Never create `CloudFlowDefinition` `.mcs.yml` stubs — they cause VS Code errors",
            "- Push = Publish via the LSP. No separate publish step.",
        ])

    def _build_agent(self, checks: dict, project_root: Path) -> str:
        return "\n".join([
            "# Build Your First Agent",
            "",
            "One file. One class. That's the whole pattern.",
            "",
            "## Step 1: Create the file",
            "",
            "Create `agents/weather_agent.py`:",
            "",
            "```python",
            "import json",
            "import urllib.request",
            "from agents.basic_agent import BasicAgent",
            "",
            "",
            "class WeatherAgent(BasicAgent):",
            "    def __init__(self):",
            "        self.name = 'Weather'",
            "        self.metadata = {",
            '            "name": self.name,',
            '            "description": "Gets current weather for a city.",',
            '            "parameters": {',
            '                "type": "object",',
            '                "properties": {',
            '                    "city": {',
            '                        "type": "string",',
            '                        "description": "City name"',
            "                    }",
            "                },",
            '                "required": ["city"]',
            "            }",
            "        }",
            "        super().__init__(name=self.name, metadata=self.metadata)",
            "",
            "    def perform(self, **kwargs):",
            "        city = kwargs.get('city', 'Seattle')",
            "        try:",
            "            url = f'https://wttr.in/{city}?format=j1'",
            "            req = urllib.request.Request(url, headers={'User-Agent': 'RAPP'})",
            "            with urllib.request.urlopen(req, timeout=10) as resp:",
            "                data = json.loads(resp.read())",
            "            current = data['current_condition'][0]",
            "            return json.dumps({",
            "                'status': 'success',",
            "                'city': city,",
            "                'temp_f': current['temp_F'],",
            "                'condition': current['weatherDesc'][0]['value'],",
            "                'humidity': current['humidity'],",
            "            })",
            "        except Exception as e:",
            "            return json.dumps({'status': 'error', 'error': str(e)})",
            "```",
            "",
            "## Step 2: There is no step 2",
            "",
            "The brainstem auto-discovers `*_agent.py` files on every request.",
            "Just save the file and chat. Ask 'What's the weather in Tokyo?'",
            "",
            "## The Contract",
            "",
            "| Required | What |",
            "|----------|------|",
            "| `self.name` | Short name (used as tool name) |",
            "| `self.metadata` | OpenAI function-calling schema |",
            "| `perform(**kwargs)` | The work — return a string |",
            "",
            "| Optional | What |",
            "|----------|------|",
            "| `system_context()` | Return a string injected into every system prompt |",
            "",
            "## Tips",
            "",
            "- The `description` in metadata is how the LLM decides when to call your agent",
            "- Return JSON strings for structured data, plain strings for text",
            "- Keep it simple — complexity goes inside `perform()`, not in the framework",
            "- Need storage? Import `AzureFileStorageManager` (shimmed to local JSON)",
            "- Need HTTP? Use `urllib.request` or `import requests`",
            "- The file is portable — copy it to another brainstem and it just works",
        ])

    def _checklist(self, checks: dict, project_root: Path) -> str:
        def mark(done): return "[x]" if done else "[ ]"

        tier = checks["current_tier"]
        lines = [
            f"# RAPP Brainstem Progress — Currently Tier {tier}",
            "",
            "## Tier 1 — Brainstem (Local)",
            "",
            f"- {mark(True)} Brainstem installed",
            f"- {mark(checks['soul_file'])} Soul file customized (`soul.md`)",
            f"- {mark(checks['env_file'])} Environment configured (`.env`)",
            f"- {mark(checks['brainstem_running'])} Server running",
            f"- {mark(checks['memory_data'])} Memory system has data",
            f"- {mark(len(checks['custom_agents']) > 0)} Custom agent created ({len(checks['custom_agents'])} found)",
            "",
            "## Tier 2 — Spinal Cord (Azure)",
            "",
            f"- {mark(checks['azure_deploy'])} ARM template exists (`azuredeploy.json`)",
            f"- {mark(checks['azure_configured'])} Azure credentials configured",
            "- [ ] Deployed to Azure Functions",
            "- [ ] Azure OpenAI connected",
            "- [ ] Azure File Share for storage",
            "",
            "## Tier 3 — Nervous System (Copilot Studio)",
            "",
            f"- {mark(checks['copilot_studio_agent'])} CopilotStudio agent installed",
            f"- {mark(checks['copilot_studio_workspace'])} Workspace exists",
            f"- {mark(checks['copilot_studio_connected'])} Connected to environment",
            f"- {mark(checks['deploy_script'])} Deploy script ready (`deploy.sh`)",
            "- [ ] Power Automate flows created (SaveMemory + RecallMemory)",
            "- [ ] Published and tested in Teams",
            "",
        ]

        if tier == 1:
            lines += ["**Next step:** Write your first custom agent (action='build-agent')"]
        elif tier == 2:
            lines += ["**Next step:** Deploy to Azure, then move to Tier 3 (action='tier3')"]
        elif tier == 3:
            lines += ["**Next step:** Deploy and test — say 'Deploy to Copilot Studio'"]

        return "\n".join(lines)
