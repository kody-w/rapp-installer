# Copilot Instructions — RAPP Brainstem

## Architecture

RAPP Brainstem is a progressive AI agent platform taught through a biological metaphor:

1. **🧠 Brainstem** (`rapp_brainstem/`) — The core. A local-first Flask server (Python 3.11) using GitHub Copilot's API for LLM inference. No API keys needed — just `gh auth login`. This is where all development happens.
2. **☁️ Spinal Cord** (`azuredeploy.json`, `deploy.sh`) — Azure deployment. ARM template creates Function App, Azure OpenAI, Storage, App Insights. All Entra ID auth.
3. **🤖 Nervous System** (`MSFTAIBASMultiAgentCopilot_*.zip`) — Power Platform solution for Copilot Studio. Connects the Azure Function to Teams and M365 Copilot.

Everything else in the repo root (install scripts, index.html, docs/) is onboarding infrastructure.

### Brainstem internals

- **`brainstem.py`** — The server. Auth, agent orchestration, tool-calling loop, all HTTP endpoints.
- **Soul file** (`soul.md`): System prompt. Users set `SOUL_PATH` in `.env` to their own.
- **Agent auto-discovery**: `*_agent.py` files in `AGENTS_PATH` extend `BasicAgent`, implement `perform()`, get registered as OpenAI function-calling tools via `to_tool()`.
- **Import shims**: `_register_shims()` injects `sys.modules` so remote agents importing `utils.azure_file_storage` or `utils.dynamics_storage` transparently get `local_storage.py`.
- **Remote agent repos**: Hot-loaded from GitHub repos via `.repos.json`. Missing pip deps auto-installed.
- **Auth chain**: env var → `.copilot_token` file → `gh auth token` CLI → device code OAuth at `/login`.

## Running & Testing

```bash
# Start the brainstem server
cd rapp_brainstem && ./start.sh    # port 7071

# Run tests
cd rapp_brainstem && python3 -m pytest test_local_agents.py -v

# Run a single test
python3 -m pytest test_local_agents.py::TestLocalStorage::test_write_and_read -v

# Health check
curl -s localhost:7071/health | python3 -m json.tool
```

## Writing Agents

Agents extend `BasicAgent` with `name`, `metadata` (OpenAI function schema), and `perform()`:

```python
from basic_agent import BasicAgent

class MyAgent(BasicAgent):
    def __init__(self):
        self.name = "MyAgent"
        self.metadata = {
            "name": self.name,
            "description": "Description the LLM reads to decide when to call this.",
            "parameters": {
                "type": "object",
                "properties": {"param1": {"type": "string", "description": "..."}},
                "required": ["param1"]
            }
        }
        super().__init__()

    def perform(self, param1="", **kwargs):
        return f"Result: {param1}"
```

- File named `*_agent.py` in agents directory
- `perform()` must accept `**kwargs`
- Agents importing `AzureFileStorageManager` get the local shim automatically

## Key Conventions

- **Python 3.11** target runtime
- **No API keys** for local dev — GitHub Copilot token exchange
- **Config via `.env`** (see `.env.example`)
- **Local-first storage**: `local_storage.py` stores to `.brainstem_data/` on disk
- **`POST /chat`** expects `{"user_input": "...", "conversation_history": [], "session_id": "..."}`
- **Skill-based onboarding**: `skill.md` follows the Moltbook pattern — frontmatter metadata, autonomous execution steps, ⏸️ pause points for user input, state saved to `~/.config/brainstem/state.json`
