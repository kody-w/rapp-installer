# CommunityRAPP — Public Skill Interface

> **This file is the public gateway to CommunityRAPP.**
> The CommunityRAPP repo (kody-w/CommunityRAPP) is private.
> This skill.md is hosted on the public rapp-installer repo so any AI agent can discover it.

---

## Identity

```
repo: kody-w/CommunityRAPP (private — contributors only)
public_gateway: kody-w/rapp-installer (this repo — public)
type: azure-functions-backend
purpose: RAPP agent runtime, pipeline, and orchestration engine
agent_registry: billwhalenmsft/RAPP-Agent-Repo
deploy_template: kody-w/rapp-installer/main/azuredeploy.json
```

---

## What CommunityRAPP Is

The **Azure Functions backend** for the RAPP (Rapid Agent Prototyping Platform) ecosystem. It takes a transcript, discovery call, or user request and turns it into a production-ready AI agent deployed on Azure — with memory, multi-user support, and Microsoft 365 integration.

---

## Deploy

One-click Azure deployment (public — anyone can use this):

```
https://portal.azure.com/#create/Microsoft.Template/uri/https%3A%2F%2Fraw.githubusercontent.com%2Fkody-w%2Frapp-installer%2Fmain%2Fazuredeploy.json
```

After deploy:
1. Copy the setup script from the Azure **Outputs** tab
2. Run it — clones repo, configures everything, deploys to Azure

---

## Architecture

```
User (Teams/M365 Copilot/Web)
  → Copilot Studio (NLP, dialog)
    → Power Automate (user context enrichment)
      → Azure Function (agent routing, memory, OpenAI)
        → Response flows back
```

### HTTP Triggers

| Endpoint | Purpose |
|----------|---------|
| `POST /api/businessinsightbot_function` | Main agent endpoint |
| `POST /api/copilot_studio_trigger` | Copilot Studio integration |

### API Contract

```json
// Request
POST /api/businessinsightbot_function
{
  "user_input": "string",
  "conversation_history": [],
  "user_guid": "optional-guid"
}

// Response
{
  "assistant_response": "formatted markdown |||VOICE||| concise voice text",
  "voice_response": "concise voice text",
  "agent_logs": "what agents did",
  "user_guid": "the-user-guid"
}
```

---

## What's Inside (for contributors with access)

### Agents (17)
Loaded from `agents/` folder. All inherit from `BasicAgent`. See the
[Agent Registry skill](agent-repo-skill.md) for the full catalog.

### Key Directories

| Directory | Purpose |
|-----------|---------|
| `agents/` | Production agents (auto-loaded on startup) |
| `utils/` | Storage, Copilot Studio API, triggers, report generation |
| `templates/` | Copilot Studio MCS templates |
| `transpiled/` | Transpiled agent output |
| `triggers/` | Event trigger definitions |
| `demos/` | Scripted demo JSON files |
| `docs/` | Full documentation suite |
| `tests/` | Test suite |

### Key Files

| File | Purpose |
|------|---------|
| `function_app.py` | Azure Function entry point (singleton OpenAI, agent caching) |
| `host.json` | Function timeout, health monitoring, HTTP scaling |
| `requirements.txt` | Python 3.11 dependencies (pydantic v2+) |
| `CONSTITUTION.md` | Repo governance — what belongs, what doesn't |
| `CHANGELOG.md` | Version history |
| `MSFTAIBASMultiAgentCopilot_1_0_0_5.zip` | Power Platform solution for Teams/M365 |

---

## Performance Features

- **Singleton OpenAI client** with 30-min TTL refresh
- **Agent caching** with 5-min TTL
- **Request timeout handling** (408 responses)
- **Flexible auth** — identity-based (Managed Identity) or key-based
- **Health monitoring** in host.json

---

## Power Platform Integration

Import `MSFTAIBASMultiAgentCopilot_1_0_0_5.zip` into Power Apps to deploy to Teams and M365 Copilot. Configure Power Automate flow with your Azure Function URL + Function Key.

---

## Compatibility

- **Python**: 3.11 (required for Azure Functions v4)
- **Runtime**: Azure Functions (Flex Consumption)
- **AI Model**: Azure OpenAI (GPT-4o, GPT-5.1+)
- **Auth**: Entra ID (Managed Identity) or key-based

---

## Getting Access

CommunityRAPP is a private repo. To get contributor access, contact a repo maintainer.

---

## Version

```
runtime_version: 2.0.0
agents: 17
last_updated: 2026-02-27
```
