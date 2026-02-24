# RAPP Brainstem

A minimal local AI agent endpoint. One dependency: a GitHub account.

## Quickstart

```bash
# 1. Authenticate with GitHub
gh auth login

# 2. Clone and start
git clone <this-repo>
cd rapp_brainstem
./start.sh
```

That's it. Your endpoint is live at `http://localhost:7071`.

---

## Talk to it

```bash
curl -X POST http://localhost:7071/chat \
  -H "Content-Type: application/json" \
  -d '{"user_input": "Hello!"}'
```

Response:
```json
{
  "response": "Hello! How can I help you today?",
  "session_id": "abc-123",
  "agent_logs": ""
}
```

---

## Plug in your private soul + agents

The brainstem is public. Your personality and logic stay private.

**1. Create your private soul file:**
```markdown
# soul.md
You are Aria, a sharp-witted assistant for Contoso's sales team.
Your tone is professional but approachable...
```

**2. Create your private agents:**
```python
# my_private_agents/crm_agent.py
from basic_agent import BasicAgent

class CRMLookupAgent(BasicAgent):
    def __init__(self):
        self.name = "CRMLookupAgent"
        self.metadata = {
            "name": self.name,
            "description": "Looks up a customer record by name or email.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Customer name or email"}
                },
                "required": ["query"]
            }
        }
        super().__init__()

    def perform(self, query="", **kwargs):
        # your logic here
        return f"Found customer: {query}"
```

**3. Point brainstem to your private files:**
```bash
# .env
SOUL_PATH=/path/to/my/private/soul.md
AGENTS_PATH=/path/to/my/private/agents
```

Then `./start.sh` — brainstem loads your soul and agents. The brainstem code never needs to change.

---

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `GITHUB_TOKEN` | auto-detected via `gh auth token` | Your GitHub PAT or Copilot token |
| `GITHUB_MODEL` | `gpt-4o-mini` | Model to use (see [GitHub Models](https://github.com/marketplace/models)) |
| `SOUL_PATH` | `./soul.md` | Path to your soul file |
| `AGENTS_PATH` | `./agents` | Path to your agents directory |
| `PORT` | `7071` | Local port |

---

## Available GitHub Models (free)

- `gpt-4o-mini` — fast, cheap, great for most tasks
- `gpt-4o` — smarter, slower
- `Phi-4` — Microsoft's small model, very fast
- `Meta-Llama-3.1-8B-Instruct` — open weights

See full list at [github.com/marketplace/models](https://github.com/marketplace/models).

---

## Writing agents

Agents are Python files named `*_agent.py` in your `AGENTS_PATH`. Extend `BasicAgent`:

```python
from basic_agent import BasicAgent

class MyAgent(BasicAgent):
    def __init__(self):
        self.name = "MyAgent"
        self.metadata = {
            "name": self.name,
            "description": "What this agent does — the LLM reads this.",
            "parameters": {
                "type": "object",
                "properties": {
                    "param1": {"type": "string", "description": "What param1 is"}
                },
                "required": ["param1"]
            }
        }
        super().__init__()

    def perform(self, param1="", **kwargs):
        # your logic
        return f"Result: {param1}"
```

The brainstem auto-discovers and registers all agents as tools. The LLM decides when to call them.

---

## Health check

```bash
curl http://localhost:7071/health
```

```json
{
  "status": "ok",
  "model": "gpt-4o-mini",
  "soul": "./soul.md",
  "agents": ["HelloAgent"],
  "token": "✓"
}
```
