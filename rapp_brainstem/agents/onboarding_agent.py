"""
Onboarding — Guides users through the RAPP Brainstem journey.

Interactive guide from first launch through all three tiers:
  Tier 1 (Brainstem)      — local Flask server, writing agents, soul file
  Tier 2 (Spinal Cord)    — Azure deployment, cloud services
  Tier 3 (Nervous System) — Copilot Studio, M365/Teams integration

Actions:
  start           — detect where the user is and suggest next steps
  tier1           — Tier 1 guide: local setup, first agent, soul file
  tier2           — Tier 2 guide: Azure deployment
  tier3           — Tier 3 guide: Copilot Studio deployment
  build-agent     — walkthrough: create a custom agent from scratch
  activate-tier3  — move CopilotStudio agent from experimental/ to agents/
  checklist       — show progress checklist across all tiers

Project structure:
  Root (8 files)     — brainstem.py, soul.md, start.sh, etc.
  agents/            — active agents (auto-discovered)
  agents/experimental/ — inactive agents (not loaded until activated)
  utilities/         — deploy scripts, test helpers

Follows the Single File Agent pattern (Constitution Article IV).
"""

import json
import shutil
from pathlib import Path

from agents.basic_agent import BasicAgent


def _detect_tier(project_root: Path) -> dict:
    """Detect which tier the user is at based on what exists."""
    agents_dir = project_root / "agents"
    experimental_dir = agents_dir / "experimental"

    checks = {
        # Tier 1 — Local
        "brainstem_running": False,
        "soul_file": (project_root / "soul.md").exists(),
        "env_file": (project_root / ".env").exists(),
        "memory_data": (project_root / ".brainstem_data").exists(),
        "custom_agents": [],

        # Tier 2 — Azure
        "azure_deploy": (project_root / "azuredeploy.json").exists(),
        "azure_configured": False,

        # Tier 3 — Copilot Studio
        "cs_agent_active": (agents_dir / "copilot_studio_agent.py").exists(),
        "cs_agent_experimental": (experimental_dir / "copilot_studio_agent.py").exists(),
        "cs_workspace": (project_root / "copilot-studio").exists(),
        "cs_connected": False,
        "deploy_script": (project_root / "utilities" / "deploy.sh").exists(),
    }

    # Check if brainstem is running
    try:
        import urllib.request
        urllib.request.urlopen("http://localhost:7071/health", timeout=2)
        checks["brainstem_running"] = True
    except Exception:
        pass

    # Count custom agents (exclude built-in)
    builtin = {"basic_agent.py", "context_memory_agent.py", "manage_memory_agent.py",
               "hacker_news_agent.py", "onboarding_agent.py", "copilot_studio_agent.py"}
    if agents_dir.exists():
        for f in agents_dir.glob("*_agent.py"):
            if f.name not in builtin:
                checks["custom_agents"].append(f.name)

    # Check Azure config
    if checks["env_file"]:
        try:
            checks["azure_configured"] = "AZURE" in (project_root / ".env").read_text(encoding="utf-8").upper()
        except Exception:
            pass

    # Check Copilot Studio connection
    conn = project_root / "copilot-studio" / "RAPP Brainstem" / ".mcs" / "conn.json"
    checks["cs_connected"] = conn.exists()

    # Determine current tier
    if checks["cs_connected"] or checks["cs_agent_active"]:
        checks["current_tier"] = 3
    elif checks["azure_configured"]:
        checks["current_tier"] = 2
    else:
        checks["current_tier"] = 1

    return checks


class OnboardingAgent(BasicAgent):
    def __init__(self):
        self.name = "Onboarding"
        self.metadata = {
            "name": self.name,
            "description": (
                "Guides users through the RAPP Brainstem journey from local "
                "setup through Azure to Copilot Studio. Detects where you are "
                "and suggests next steps. Use activate-tier3 when ready to "
                "enable Copilot Studio deployment."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "description": "What to show or do.",
                        "enum": ["start", "tier1", "tier2", "tier3",
                                 "build-agent", "activate-tier3", "checklist"]
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
            "activate-tier3": self._activate_tier3,
            "checklist": self._checklist,
        }
        return handlers.get(action, self._start)(checks, project_root)

    # -- start --------------------------------------------------------------

    def _start(self, checks: dict, root: Path) -> str:
        tier = checks["current_tier"]
        lines = [
            "# Welcome to RAPP Brainstem",
            "",
            f"You're at **Tier {tier}**.",
            "",
        ]
        lines += self._status_block(checks)

        if tier == 1:
            if not checks["brainstem_running"]:
                lines += ["## Get Started", "",
                          "```bash", "./start.sh", "```", ""]
            lines += [
                "## What's Next?", "",
                "- **Write your first agent** — action='build-agent'",
                "- **Customize your soul** — edit `soul.md`",
                "- **Check progress** — action='checklist'",
                "- **When ready to scale** — action='tier2' or action='tier3'",
            ]
        elif tier == 2:
            lines += [
                "## What's Next?", "",
                "- **Deploy to Azure** — `az deployment group create`",
                "- **Move to Tier 3** — action='tier3'",
            ]
        elif tier == 3:
            if not checks["cs_agent_active"]:
                lines += [
                    "## Activate Copilot Studio", "",
                    "The CopilotStudio agent is in `agents/experimental/`.",
                    "Run action='activate-tier3' to move it to the active agents folder.",
                    "",
                ]
            else:
                lines += [
                    "## What's Next?", "",
                    "- **Deploy** — say 'deploy to Copilot Studio'",
                    "- **Check status** — say 'Copilot Studio status'",
                ]

        return "\n".join(lines)

    # -- tier1 --------------------------------------------------------------

    def _tier1(self, checks: dict, root: Path) -> str:
        return "\n".join([
            "# Tier 1 — The Brainstem", "",
            "Local-first AI agent server. No cloud needed.", "",
            "## Project Structure", "",
            "```",
            "brainstem.py          # The engine (Flask, port 7071)",
            "soul.md               # AI personality (system prompt)",
            "local_storage.py      # JSON memory storage",
            "start.sh              # One-command launcher",
            "index.html            # Web UI",
            "requirements.txt      # Python deps (flask, requests, dotenv)",
            "agents/               # Active agents (auto-discovered)",
            "  basic_agent.py      #   Base class",
            "  context_memory_agent.py",
            "  manage_memory_agent.py",
            "  hacker_news_agent.py",
            "  onboarding_agent.py",
            "  experimental/       #   Inactive (not loaded)",
            "    copilot_studio_agent.py",
            "    copilot_research_agent.py",
            "    learn_new_agent.py",
            "utilities/            # Scripts and helpers",
            "  deploy.sh           #   Copilot Studio deploy script",
            "```", "",
            "## Quick Start", "",
            "1. **Install** — `curl -fsSL https://kody-w.github.io/rapp-installer/install.sh | bash`",
            "2. **Start** — `./start.sh`",
            "3. **Open** — http://localhost:7071",
            "4. **Chat** — the AI loads `soul.md` and discovers all agents", "",
            "## Auth", "",
            "GitHub account with Copilot access. Three ways:",
            "- `GITHUB_TOKEN` in `.env`",
            "- Device code login (web UI shows the code)",
            "- `gh auth login` (GitHub CLI)", "",
            "## Built-in Agents", "",
            "| Agent | What It Does |",
            "|-------|-------------|",
            "| ContextMemory | Recalls stored memories |",
            "| ManageMemory | Saves facts, preferences, insights |",
            "| HackerNews | Fetches top 10 HN stories |",
            "| Onboarding | This guide |", "",
            "## Your First Agent", "",
            "Ask me with action='build-agent'.",
        ] + [""] + self._status_block(checks))

    # -- tier2 --------------------------------------------------------------

    def _tier2(self, checks: dict, root: Path) -> str:
        has_arm = checks["azure_deploy"]
        return "\n".join([
            "# Tier 2 — The Spinal Cord", "",
            "Deploy to Azure. Same agents, cloud scale.", "",
            "| Local (Tier 1) | Azure (Tier 2) |",
            "|----------------|----------------|",
            "| Flask on localhost | Azure Functions |",
            "| GitHub Copilot API | Azure OpenAI |",
            "| JSON file storage | Azure File Share |",
            "| Single user | Multi-user with auth |", "",
            "## Steps", "",
            "1. **Configure** `.env` with Azure variables",
            "2. **Deploy** — `az deployment group create --template-file azuredeploy.json`",
            "3. **Verify** — health endpoint on the Function App",
            "4. **Agents** — your `*_agent.py` files work unchanged", "",
            f"ARM template: **{'found' if has_arm else 'not found'}**", "",
            "When ready for M365/Teams — action='tier3'.",
        ])

    # -- tier3 --------------------------------------------------------------

    def _tier3(self, checks: dict, root: Path) -> str:
        active = checks["cs_agent_active"]
        experimental = checks["cs_agent_experimental"]
        connected = checks["cs_connected"]

        lines = [
            "# Tier 3 — The Nervous System", "",
            "Publish to Copilot Studio. Reach M365, Teams, and the enterprise.", "",
            "| Tier 1-2 | Tier 3 (Copilot Studio) |",
            "|----------|------------------------|",
            "| Python agents | YAML topics + Power Automate flows |",
            "| JSON storage | OOTB Dataverse Notes table |",
            "| Flask API | Copilot Studio generative AI |",
            "| Browser UI | Teams, M365 Copilot |", "",
        ]

        if not active and experimental:
            lines += [
                "## Step 1: Activate the CopilotStudio Agent", "",
                "The agent is in `agents/experimental/` — it won't load until activated.", "",
                "**Run action='activate-tier3'** to move it to the active agents folder.", "",
            ]
        elif active:
            lines += [
                "## CopilotStudio Agent: Active", "",
                "The agent is loaded and ready. It handles:", "",
                "- **deploy** — generate YAML + push to cloud (push = publish)",
                "- **generate** — write YAML without pushing",
                "- **push / pull / changes** — cloud sync",
                "- **scan / preview / export** — Python agent introspection",
                "- **status** — check readiness", "",
            ]

        lines += [
            "## Setup (one-time)", "",
            "1. Clone an agent from [copilotstudio.microsoft.com](https://copilotstudio.microsoft.com) via VS Code extension",
            "2. This creates `.mcs/conn.json` with your environment connection",
            "3. Create SaveMemory + RecallMemory Power Automate flows in the portal",
            "4. Pull to sync flow GUIDs, then deploy", "",
            "## Deploy", "",
            "```",
            "> Deploy to Copilot Studio",
            "```", "",
            "Or: `utilities/deploy.sh`", "",
            "## Dataverse Storage (OOTB)", "",
            "No custom tables. Uses built-in Notes (annotation):",
            "- `subject` = memory type (rapp:fact, rapp:preference, etc.)",
            "- `notetext` = content with importance prefix",
            "- `createdon` = automatic timestamp",
            "- `_createdby` = automatic user scoping",
            "- Filter: `contains(subject,'rapp:')`", "",
            "## Status", "",
            f"- CopilotStudio agent: **{'active' if active else 'experimental' if experimental else 'missing'}**",
            f"- Environment connected: **{'yes' if connected else 'no'}**",
            f"- Deploy script: **{'ready' if checks['deploy_script'] else 'not found'}**", "",
            "## Lessons Learned", "",
            "- All inputs: `StringPrebuiltEntity` with `Coalesce()` null guards",
            "- `inputType`/`outputType` blocks required for `Topic.*` Power Fx vars",
            "- Flow inputs use generic keys (`text`, `text_1`) not friendly names",
            "- No `CloudFlowDefinition` stubs — they cause VS Code errors",
            "- Push = Publish via LSP. No separate publish step.",
        ]
        return "\n".join(lines)

    # -- build-agent --------------------------------------------------------

    def _build_agent(self, checks: dict, root: Path) -> str:
        return "\n".join([
            "# Build Your First Agent", "",
            "One file. One class. That's it.", "",
            "## Create `agents/weather_agent.py`:", "",
            "```python",
            "import json",
            "import urllib.request",
            "from agents.basic_agent import BasicAgent", "",
            "class WeatherAgent(BasicAgent):",
            "    def __init__(self):",
            "        self.name = 'Weather'",
            "        self.metadata = {",
            '            "name": self.name,',
            '            "description": "Gets current weather for a city.",',
            '            "parameters": {',
            '                "type": "object",',
            '                "properties": {',
            '                    "city": {"type": "string", "description": "City name"}',
            "                },",
            '                "required": ["city"]',
            "            }",
            "        }",
            "        super().__init__(name=self.name, metadata=self.metadata)", "",
            "    def perform(self, **kwargs):",
            "        city = kwargs.get('city', 'Seattle')",
            "        try:",
            "            url = f'https://wttr.in/{city}?format=j1'",
            "            req = urllib.request.Request(url, headers={'User-Agent': 'RAPP'})",
            "            with urllib.request.urlopen(req, timeout=10) as resp:",
            "                data = json.loads(resp.read())",
            "            c = data['current_condition'][0]",
            "            return json.dumps({'status': 'success', 'city': city,",
            "                'temp_f': c['temp_F'], 'condition': c['weatherDesc'][0]['value']})",
            "        except Exception as e:",
            "            return json.dumps({'status': 'error', 'error': str(e)})",
            "```", "",
            "## That's it", "",
            "Save the file. Ask 'What's the weather in Tokyo?'",
            "Auto-discovered on the next request. No restart needed.", "",
            "## The Contract", "",
            "| Required | What |",
            "|----------|------|",
            "| `self.name` | Tool name |",
            "| `self.metadata` | OpenAI function-calling schema |",
            "| `perform(**kwargs)` | Do the work, return a string |", "",
            "| Optional | What |",
            "|----------|------|",
            "| `system_context()` | String injected into every system prompt |", "",
            "The file is portable — copy it to another brainstem and it just works.",
        ])

    # -- activate-tier3 -----------------------------------------------------

    def _activate_tier3(self, checks: dict, root: Path) -> str:
        agents_dir = root / "agents"
        experimental = agents_dir / "experimental" / "copilot_studio_agent.py"
        target = agents_dir / "copilot_studio_agent.py"

        if target.exists():
            return json.dumps({
                "status": "already_active",
                "message": "CopilotStudio agent is already in agents/ and active.",
            })

        if not experimental.exists():
            return json.dumps({
                "status": "error",
                "message": "copilot_studio_agent.py not found in agents/experimental/.",
            })

        # Move from experimental to active
        shutil.move(str(experimental), str(target))

        # Also move deploy.sh to utilities if not there
        deploy_src = root / "deploy.sh"
        deploy_dst = root / "utilities" / "deploy.sh"
        if deploy_src.exists() and not deploy_dst.exists():
            (root / "utilities").mkdir(exist_ok=True)
            shutil.move(str(deploy_src), str(deploy_dst))

        return json.dumps({
            "status": "success",
            "message": (
                "CopilotStudio agent activated. It will load on the next /chat request.\n\n"
                "You now have access to:\n"
                "- 'Deploy to Copilot Studio' — generates YAML + pushes to cloud\n"
                "- 'Copilot Studio status' — check readiness\n"
                "- 'Scan agents for Copilot Studio' — introspect Python agents\n\n"
                "Next: clone an agent from copilotstudio.microsoft.com via the VS Code extension, "
                "then say 'deploy to Copilot Studio'."
            ),
        })

    # -- checklist ----------------------------------------------------------

    def _checklist(self, checks: dict, root: Path) -> str:
        def x(done): return "[x]" if done else "[ ]"

        tier = checks["current_tier"]
        custom = checks["custom_agents"]
        cs_ready = checks["cs_agent_active"] or checks["cs_agent_experimental"]

        lines = [
            f"# RAPP Brainstem Progress — Tier {tier}", "",
            "## Tier 1 — Brainstem (Local)", "",
            f"- {x(True)} Installed",
            f"- {x(checks['soul_file'])} Soul file (`soul.md`)",
            f"- {x(checks['env_file'])} Environment (`.env`)",
            f"- {x(checks['brainstem_running'])} Server running",
            f"- {x(checks['memory_data'])} Memory has data",
            f"- {x(len(custom) > 0)} Custom agent ({len(custom)} found)", "",
            "## Tier 2 — Spinal Cord (Azure)", "",
            f"- {x(checks['azure_deploy'])} ARM template",
            f"- {x(checks['azure_configured'])} Azure configured", "",
            "## Tier 3 — Nervous System (Copilot Studio)", "",
            f"- {x(cs_ready)} CopilotStudio agent ({'active' if checks['cs_agent_active'] else 'experimental' if checks['cs_agent_experimental'] else 'missing'})",
            f"- {x(checks['cs_connected'])} Connected to environment",
            f"- {x(checks['deploy_script'])} Deploy script (`utilities/deploy.sh`)", "",
        ]

        if tier == 1:
            lines += ["**Next:** action='build-agent'"]
        elif tier == 2:
            lines += ["**Next:** action='tier3'"]
        elif tier == 3 and not checks["cs_agent_active"]:
            lines += ["**Next:** action='activate-tier3' to enable CopilotStudio agent"]
        elif tier == 3:
            lines += ["**Next:** Say 'deploy to Copilot Studio'"]

        return "\n".join(lines)

    # -- helpers ------------------------------------------------------------

    def _status_block(self, checks: dict) -> list[str]:
        r = "running" if checks["brainstem_running"] else "not running"
        c = checks["custom_agents"]
        cs = "active" if checks["cs_agent_active"] else "experimental" if checks["cs_agent_experimental"] else "—"
        return [
            "## Status", "",
            f"- Server: **{r}**",
            f"- Soul: **{'ok' if checks['soul_file'] else 'missing'}**",
            f"- Memory: **{'has data' if checks['memory_data'] else 'empty'}**",
            f"- Custom agents: **{len(c)}**",
            f"- CopilotStudio: **{cs}**",
            "",
        ]
