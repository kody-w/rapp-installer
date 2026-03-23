# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

RAPP Brainstem is a local-first AI agent platform — a Flask server that uses GitHub Copilot as its LLM backbone. It's an **engine, not a consumer product** (see CONSTITUTION.md). Agents are single Python files auto-discovered at request time. No API keys beyond a GitHub account with Copilot access.

## Commands

```bash
# Run the server
./start.sh                    # macOS/Linux
python3 brainstem.py          # direct

# Run all tests
python3 -m pytest test_local_agents.py -v

# Run a single test
python3 -m pytest test_local_agents.py::TestLocalStorage::test_write_and_read -v

# Install dependencies
pip3 install -r requirements.txt

# Health check
curl -s localhost:7071/health | python3 -m json.tool
```

## Architecture

Everything runs through `brainstem.py` (~1100 lines) — the single Flask server that handles auth, agent discovery, the LLM tool-calling loop, and all API endpoints.

### Request Flow (POST /chat)
1. Load `soul.md` as system prompt
2. Scan `agents/` for `*_agent.py` files (top-level only, fresh every request)
3. Register discovered agents as OpenAI function-calling tools
4. Call Copilot API with messages + tools
5. If LLM returns `tool_calls` → execute agents → append results → loop (max 3 rounds)
6. Return final text response + agent logs

### Auth Chain (first match wins)
1. `GITHUB_TOKEN` env var
2. `.copilot_token` file (persisted from device-code login)
3. `gh auth token` CLI output

GitHub token → exchanged for short-lived Copilot API token → cached in memory and `.copilot_session`

### Import Shimming
Cloud dependencies are shimmed to local equivalents at startup via `sys.modules`:
- `utils.azure_file_storage` → `local_storage.py`
- `utils.dynamics_storage` → `local_storage.py`
- `agents.basic_agent` / `openrappter.agents.basic_agent` → local `basic_agent.py`

This lets Azure-deployed agents run locally without code changes.

### Auto-Dependency Installation
When an agent imports a missing package, the server catches `ModuleNotFoundError`, maps the import name to a pip package (e.g., `bs4` → `beautifulsoup4`), installs it, and retries.

## Agent Contract

Agents are `*_agent.py` files in `agents/` (not subdirectories — `agents/experimental/` is excluded from discovery).

```python
from basic_agent import BasicAgent

class MyAgent(BasicAgent):
    def __init__(self):
        self.name = "MyAgent"
        self.metadata = {
            "name": self.name,
            "description": "What the LLM sees to decide when to call this",
            "parameters": {
                "type": "object",
                "properties": {
                    "arg": {"type": "string", "description": "..."}
                },
                "required": ["arg"]
            }
        }
        super().__init__()

    def perform(self, arg="", **kwargs):
        return "string result the LLM sees"
```

- `perform()` must accept `**kwargs` and return a string
- Optional `system_context()` → returns string injected into the system prompt each turn
- The `metadata.description` is critical — it's what the LLM reads to decide when to invoke the agent

## Key Files

| File | Role |
|------|------|
| `brainstem.py` | Core server: auth, LLM loop, agent discovery, all endpoints |
| `agents/basic_agent.py` | Base class all agents extend |
| `local_storage.py` | Local file storage shim (mirrors Azure File Storage API) |
| `soul.md` | Default system prompt (user replaces with their own) |
| `index.html` | Built-in chat web UI |
| `test_local_agents.py` | Tests: storage, shim registration, agent loading, auth |
| `.env` / `.env.example` | Config (GITHUB_TOKEN, GITHUB_MODEL, PORT, SOUL_PATH, AGENTS_PATH) |
| `VERSION` | Semver string — the entire release process is editing this file |

## Scope Rules (from CONSTITUTION.md)

- This repo is the **engine only** — no consumer brand identities, mascots, educational platforms, or background daemons
- The one-liner install must never break — test changes against it
- Local data stays on the user's device; no telemetry, no phoning home
- Complexity belongs inside `perform()`, not in the framework
