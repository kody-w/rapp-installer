import sys
import os
import json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from basic_agent import BasicAgent

# Resolve paths relative to the brainstem directory
_BRAINSTEM_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_REPO_ROOT = os.path.dirname(_BRAINSTEM_DIR) if os.path.basename(_BRAINSTEM_DIR) == "rapp_brainstem" else _BRAINSTEM_DIR
_SKILL_PATH = os.path.join(_REPO_ROOT, "skill.md")
_STATE_PATH = os.path.expanduser("~/.config/brainstem/state.json")


class OnboardingAgent(BasicAgent):
    """Guides users through the RAPP Brainstem journey — reads skill.md and tracks their progress."""

    def __init__(self):
        self.name = "OnboardingGuide"
        self.metadata = {
            "name": self.name,
            "description": (
                "Helps the user understand where they are in the RAPP Brainstem journey and what to do next. "
                "Call this when the user asks for help, says 'what can I do', 'what's next', 'guide me', "
                "'how do I deploy', 'how do I install', 'set up', or needs orientation. "
                "Reads the skill.md guide and their saved progress."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "topic": {
                        "type": "string",
                        "description": "What the user is asking about: 'status', 'next', 'agents', 'azure', 'copilot-studio', 'soul', 'install', or 'overview'"
                    }
                },
                "required": []
            }
        }
        super().__init__()

    def _read_state(self):
        if os.path.exists(_STATE_PATH):
            try:
                with open(_STATE_PATH) as f:
                    return json.load(f)
            except Exception:
                pass
        return {"tier": 1, "status": "fresh"}

    def _read_skill_section(self, tier=None):
        if not os.path.exists(_SKILL_PATH):
            return None
        with open(_SKILL_PATH) as f:
            content = f.read()
        if tier == 1:
            start = content.find("## 🧠 Tier 1")
            end = content.find("## ☁️ Tier 2")
        elif tier == 2:
            start = content.find("## ☁️ Tier 2")
            end = content.find("## 🤖 Tier 3")
        elif tier == 3:
            start = content.find("## 🤖 Tier 3")
            end = content.find("## Cleanup")
        else:
            return content[:2000]
        if start == -1:
            return None
        return content[start:end] if end != -1 else content[start:]

    def perform(self, topic="status", **kwargs):
        state = self._read_state()
        tier = state.get("tier", 1)
        status = state.get("status", "fresh")

        if topic == "overview":
            return (
                "🧠 RAPP Brainstem — your AI agent journey has 3 tiers:\n\n"
                "**Tier 1: The Brainstem (local)** — You're running a local AI agent server. "
                "It has a soul (system prompt), auto-discovers agents, and uses GitHub Copilot for AI. "
                "This is where you learn agents, tool-calling, and prompt engineering.\n\n"
                "**Tier 2: The Spinal Cord (Azure)** — Deploy to Azure for always-on, persistent storage, "
                "and Azure OpenAI. Learn ARM templates, Functions, managed identity.\n\n"
                "**Tier 3: The Nervous System (Copilot Studio)** — Connect to Teams and M365 Copilot. "
                "Your local agent logic goes enterprise-wide.\n\n"
                f"📍 You're currently at **Tier {tier}** ({status})."
            )

        if topic == "status":
            azure = state.get("azure", {})
            lines = [f"📍 **Tier {tier}** — {status}"]
            lines.append(f"   Local: http://localhost:7071")
            if azure.get("function_app"):
                lines.append(f"   Azure: https://{azure['function_app']}.azurewebsites.net")
            if state.get("copilot_studio"):
                lines.append("   Copilot Studio: ✓ connected")
            return "\n".join(lines)

        if topic == "next":
            if tier == 1 and status == "fresh":
                return (
                    "🧠 **You're just getting started!** Here's what to try:\n\n"
                    "1. **Edit your soul** — open `soul.md` and give your AI a personality\n"
                    "2. **Write an agent** — copy `agents/hello_agent.py` and make it do something useful\n"
                    "3. **Connect a repo** — click ⚡ Sources in the chat UI and paste a GitHub repo URL\n\n"
                    "When you're comfortable, say **'deploy to Azure'** to move to Tier 2."
                )
            if tier == 1:
                return (
                    "☁️ **Ready for Tier 2?** Say 'deploy to Azure' to give your brainstem a cloud body.\n\n"
                    "This will create an Azure Function App, Azure OpenAI, and Storage Account — "
                    "all using managed identity (no API keys)."
                )
            if tier == 2:
                return (
                    "🤖 **Ready for Tier 3?** Say 'connect to Copilot Studio' to wire your agent into Teams and M365 Copilot.\n\n"
                    "You'll import a Power Platform solution and publish your agent to your organization."
                )
            return "🎉 **You've completed all 3 tiers!** Your agent is live in M365. Keep adding agents and refining your soul."

        if topic == "agents":
            return (
                "**Writing agents:**\n\n"
                "1. Create a file named `*_agent.py` in your agents directory\n"
                "2. Extend `BasicAgent`, define `name`, `metadata` (with OpenAI function schema), and `perform()`\n"
                "3. The brainstem auto-discovers it on startup — no registration needed\n"
                "4. `perform()` must accept `**kwargs` for forward compatibility\n\n"
                "**Example:** Look at `agents/hello_agent.py` as a template.\n\n"
                "**Remote agents:** Click ⚡ Sources in the chat UI to connect GitHub repos with agent code."
            )

        if topic == "soul":
            return (
                "**Your soul file** (`soul.md`) is the system prompt — it defines who your AI is.\n\n"
                "Tips:\n"
                "- Be specific about personality, tone, and expertise\n"
                "- List what it should and shouldn't do\n"
                "- Include domain knowledge or context\n"
                "- Point `SOUL_PATH` in `.env` to your own private soul file\n\n"
                "The default soul is in `soul.md` in the brainstem directory."
            )

        if topic == "install":
            skill_url = "https://raw.githubusercontent.com/kody-w/rapp-installer/main/skill.md"
            return (
                "**Install RAPP Brainstem** — pick your path:\n\n"
                "**One-liner (macOS/Linux):**\n"
                "```\ncurl -fsSL https://kody-w.github.io/rapp-installer/install.sh | bash\n```\n\n"
                "**One-liner (Windows PowerShell):**\n"
                "```\nirm https://raw.githubusercontent.com/kody-w/rapp-installer/main/install.ps1 | iex\n```\n"
                "Works on a factory Windows 11 PC — auto-installs Python, Git & GitHub CLI via winget.\n\n"
                "**Via GitHub Copilot CLI (guided):**\n"
                f"```\nRead {skill_url} and follow the instructions\n```\n"
                "This gives you a step-by-step guided install with an AI assistant walking you through each tier.\n\n"
                "**After install:**\n"
                "1. `gh auth login` — authenticate with GitHub\n"
                "2. `brainstem` — start the server\n"
                "3. Open http://localhost:7071\n\n"
                f"**Full guide:** {skill_url}"
            )

        if topic in ("azure", "copilot-studio"):
            t = 2 if topic == "azure" else 3
            section = self._read_skill_section(t)
            if section:
                # Return the first ~1500 chars of the relevant tier guide
                return section[:1500]
            return f"Read the full guide at: https://github.com/kody-w/rapp-installer/blob/main/skill.md"

        return self.perform(topic="overview", **kwargs)
