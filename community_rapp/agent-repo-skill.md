# RAPP Agent Registry — Public Skill Interface

> **This file is the public gateway to the RAPP Agent Registry.**
> The agent registry repo (billwhalenmsft/RAPP-Agent-Repo) is private.
> This skill.md is hosted on the public rapp-installer repo so any AI agent can discover it.

---

## Repo Identity

```
registry_repo: billwhalenmsft/RAPP-Agent-Repo (private — contributors only)
public_gateway: kody-w/rapp-installer (this repo — public)
type: agent-registry
compatible_with: kody-w/CommunityRAPP
agent_base_class: BasicAgent (@rapp/basic-agent)
package_structure: agents/@publisher/slug.py (single file, __manifest__ embedded)
```

---

## Access Model

The RAPP Agent Registry is a **private repo** — only contributors with GitHub access can fetch agents directly. This public skill.md provides:

1. **The full agent catalog** (below) so AI agents know what's available
2. **Install instructions** for contributors with access
3. **The agent manifest format** so anyone can build compatible agents

### If you have contributor access:

```
Registry:  https://raw.githubusercontent.com/billwhalenmsft/RAPP-Agent-Repo/main/registry.json
Agent:     https://raw.githubusercontent.com/billwhalenmsft/RAPP-Agent-Repo/main/agents/@publisher/slug.py
Skill:     https://raw.githubusercontent.com/billwhalenmsft/RAPP-Agent-Repo/main/skill.md
```

### If you don't have access:

Contact a repo maintainer to request contributor access, or fork and build your own agents following the manifest format below.

---

## Agent Catalog (17 agents, 3 publishers, 5 categories)

### 🧠 Core — Memory & Orchestration

| Package | Description | Author |
|---------|-------------|--------|
| `@kody/context-memory` | Recalls conversation history and stored memories | Kody Wildfeuer |
| `@kody/manage-memory` | Stores facts, preferences, insights to persistent memory | Kody Wildfeuer |
| `@kody/github-agent-library` | Browse, search, install agents from the registry via chat | Kody Wildfeuer |

### 🔧 Pipeline — RAPP Agent Factory

| Package | Description | Author |
|---------|-------------|--------|
| `@billwhalen/rapp-pipeline` | Full RAPP pipeline — transcript → agent, discovery, MVP, code gen, QG1-QG6 | Bill Whalen |
| `@billwhalen/agent-generator` | Auto-generates new agents from configurations | Bill Whalen |
| `@billwhalen/agent-transpiler` | Converts agents between M365 Copilot, Copilot Studio, Azure AI Foundry | Bill Whalen |
| `@billwhalen/copilot-studio-transpiler` | Transpiles to native Copilot Studio without Azure Function dependency | Bill Whalen |
| `@billwhalen/project-tracker` | RAPP project management and engagement tracking | Bill Whalen |

### 🔌 Integrations — Microsoft 365 & CRM

| Package | Description | Author |
|---------|-------------|--------|
| `@billwhalen/dynamics-crud` | Dynamics 365 CRUD — accounts, contacts, opportunities, leads, tasks | Bill Whalen |
| `@billwhalen/sharepoint-contract-analysis` | Contract analysis from Azure File Storage / SharePoint | Bill Whalen |
| `@billwhalen/sales-assistant` | Natural language sales CRM assistant | Bill Whalen |
| `@billwhalen/email-drafting` | Email drafting with Power Automate delivery | Bill Whalen |

### 📊 Productivity — Content & Demos

| Package | Description | Author |
|---------|-------------|--------|
| `@billwhalen/powerpoint-generator` | Template-based PowerPoint generation (Microsoft design) | Bill Whalen |
| `@billwhalen/architecture-diagram` | Architecture diagram visualization (Mermaid, SVG, ASCII) | Bill Whalen |
| `@billwhalen/scripted-demo` | Interactive demo automation from JSON scripts | Bill Whalen |
| `@billwhalen/demo-script-generator` | Generates demo script JSON files for ScriptedDemoAgent | Bill Whalen |

### 🛠️ Dev Tools

| Package | Description | Author |
|---------|-------------|--------|
| `@rapp/basic-agent` | Base class — every agent inherits from this | RAPP Core |

---

## Autonomous Install Workflow (for contributors with access)

```
User: "Install the dynamics agent"

1. GET https://raw.githubusercontent.com/billwhalenmsft/RAPP-Agent-Repo/main/registry.json
   (requires GitHub auth with repo access)
2. Search agents[] for "dynamics" in name/tags/description
3. Match: @billwhalen/dynamics-crud
4. GET https://raw.githubusercontent.com/billwhalenmsft/RAPP-Agent-Repo/main/agents/@billwhalen/dynamics-crud.py
5. Save as dynamics_crud_agent.py in CommunityRAPP agents/
6. Check requires_env — warn if non-empty
7. Report: "Installed @billwhalen/dynamics-crud v1.0.0"
```

---

## Agent Manifest Format

Every agent is a single `.py` file with a `__manifest__` dict:

```python
__manifest__ = {
    "schema": "rapp-agent/1.0",
    "name": "@yourname/my-agent",
    "version": "1.0.0",
    "display_name": "MyAgent",
    "description": "What this agent does.",
    "author": "Your Name",
    "tags": ["category", "keyword"],
    "category": "integrations",
    "quality_tier": "community",
    "requires_env": [],
    "dependencies": ["@rapp/basic-agent"],
}
```

---

## Version

```
total_agents: 17
publishers: 3 (@kody, @billwhalen, @rapp)
categories: 5 (core, pipeline, integrations, productivity, devtools)
last_updated: 2026-02-27
```
