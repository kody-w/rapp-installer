"""
CopilotStudioExport — Migrates Python agents to Copilot Studio YAML.

Scans agents/*_agent.py, introspects each class, generates natural-language
specs and Copilot Studio topic YAML. Follows the Single File Agent pattern
(Constitution Article IV). Re-run whenever agents change.

Actions:
  list    — show discovered agents and their classifications
  preview — show what would be generated (specs + YAML) without writing
  export  — write all files to copilot-studio/RAPP Brainstem/
"""

import ast
import json
import re
import shutil
import textwrap
from pathlib import Path

from agents.basic_agent import BasicAgent


# ---------------------------------------------------------------------------
# Agent classification
# ---------------------------------------------------------------------------

CLASSIFICATION_MEMORY = "memory"
CLASSIFICATION_API = "api"
CLASSIFICATION_CLI = "cli"
CLASSIFICATION_META = "meta"
CLASSIFICATION_CONTEXT = "context"

EXCLUDED_FILES = {"basic_agent.py", "copilot_studio_export_agent.py", "copilot_studio_deploy_agent.py", "copilot_studio_test_agent.py"}

# Maps Python agent name → Copilot Studio topic file name
TOPIC_NAME_MAP = {
    "ContextMemory": "RecallMemory",
    "ManageMemory": "SaveMemory",
    "HackerNews": "HackerNews",
    "CopilotResearch": "OnlineResearch",
}


def _classify_source(source: str) -> list[str]:
    """Return classification tags for an agent's source code."""
    tags = []
    if "AzureFileStorageManager" in source:
        tags.append(CLASSIFICATION_MEMORY)
    if any(tok in source for tok in ("requests.get", "requests.post", "urllib.request", "urllib.urlopen")):
        tags.append(CLASSIFICATION_API)
    if "subprocess" in source:
        tags.append(CLASSIFICATION_CLI)
    if "importlib" in source or "spec_from_file_location" in source:
        tags.append(CLASSIFICATION_META)
    if "def system_context" in source and "return None" not in source.split("def system_context")[1].split("def ")[0]:
        tags.append(CLASSIFICATION_CONTEXT)
    return tags or ["generic"]


def _should_migrate(tags: list[str], agent_name: str) -> tuple[bool, str]:
    """Decide whether an agent migrates and why."""
    if CLASSIFICATION_META in tags:
        return False, "Meta-agent that generates Python files at runtime — no Copilot Studio equivalent"
    if agent_name == "LearnNew":
        return False, "Generates Python files at runtime — no Copilot Studio equivalent"
    return True, ""


# ---------------------------------------------------------------------------
# AST-based introspection
# ---------------------------------------------------------------------------

def _extract_agent_info(file_path: Path) -> dict | None:
    """Parse a *_agent.py and extract name, metadata, classifications."""
    source = file_path.read_text(encoding="utf-8")
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None

    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        # Find classes that inherit from BasicAgent (directly or indirectly)
        if not any(
            (isinstance(b, ast.Name) and b.id == "BasicAgent") or
            (isinstance(b, ast.Attribute) and b.attr == "BasicAgent")
            for b in node.bases
        ):
            continue

        info = {
            "class_name": node.name,
            "file": file_path.name,
            "source": source,
            "tags": _classify_source(source),
        }

        # Extract self.name and self.metadata from __init__
        for item in ast.walk(node):
            if isinstance(item, ast.Assign):
                for target in item.targets:
                    if isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name):
                        if target.value.id == "self" and target.attr == "name" and isinstance(item.value, ast.Constant):
                            info["name"] = item.value.value
                        if target.value.id == "self" and target.attr == "metadata" and isinstance(item.value, ast.Dict):
                            # Evaluate metadata dict via literal_eval on the source slice
                            try:
                                meta_src = ast.get_source_segment(source, item.value)
                                if meta_src:
                                    # Replace self.name references for literal_eval
                                    meta_src = meta_src.replace("self.name", repr(info.get("name", "Unknown")))
                                    info["metadata"] = ast.literal_eval(meta_src)
                            except Exception:
                                pass

        if "name" not in info:
            # Fallback: derive from class name
            info["name"] = node.name.replace("Agent", "")

        if "metadata" not in info:
            info["metadata"] = {"name": info["name"], "description": "", "parameters": {"type": "object", "properties": {}}}

        migrate, reason = _should_migrate(info["tags"], info["name"])
        info["migrates"] = migrate
        info["exclude_reason"] = reason

        return info

    return None


# ---------------------------------------------------------------------------
# Spec generation (Phase 1)
# ---------------------------------------------------------------------------

def _generate_spec(info: dict) -> str:
    """Generate a natural-language markdown spec for one agent."""
    meta = info["metadata"]
    name = info["name"]
    desc = meta.get("description", "No description.")
    params = meta.get("parameters", {}).get("properties", {})
    required = meta.get("parameters", {}).get("required", [])
    tags = info["tags"]

    lines = [
        f"# {name} Agent — Migration Spec",
        "",
        f"**Source:** `{info['file']}`  ",
        f"**Classification:** {', '.join(tags)}  ",
        f"**Migrates:** {'Yes' if info['migrates'] else 'No — ' + info['exclude_reason']}",
        "",
        "## Purpose",
        "",
        desc,
        "",
    ]

    if params:
        lines += ["## Parameters", ""]
        for pname, pdef in params.items():
            req_marker = " *(required)*" if pname in required else ""
            ptype = pdef.get("type", "string")
            pdesc = pdef.get("description", "")
            enum_vals = pdef.get("enum")
            enum_str = f" — one of: {', '.join(f'`{v}`' for v in enum_vals)}" if enum_vals else ""
            lines.append(f"- **`{pname}`** (`{ptype}`){req_marker}: {pdesc}{enum_str}")
        lines.append("")

    # Behavior notes based on classification
    lines += ["## Behavior", ""]
    if CLASSIFICATION_MEMORY in tags:
        lines += [
            "- Reads/writes JSON via AzureFileStorageManager (Azure File Share)",
            "- In Copilot Studio: replace with Dataverse table + Power Automate flow",
            "- Memory entries have: message, theme (memory_type), date, time",
        ]
    if CLASSIFICATION_API in tags:
        lines += [
            "- Makes HTTP API calls in perform()",
            "- In Copilot Studio: replace with Power Automate cloud flow (HTTP connector)",
        ]
    if CLASSIFICATION_CLI in tags:
        lines += [
            "- Shells out to CLI tools via subprocess",
            "- In Copilot Studio: map to native capability (e.g. webBrowsing) or exclude",
        ]
    if CLASSIFICATION_CONTEXT in tags:
        lines += [
            "- Provides system_context() injected into every turn",
            "- In Copilot Studio: model as Dataverse knowledge source + agent instructions",
        ]
    if CLASSIFICATION_META in tags:
        lines += [
            "- Meta-agent that creates/manages other agents at runtime",
            "- No Copilot Studio equivalent — excluded from migration",
        ]

    lines.append("")

    # Key behaviors to preserve
    if name == "ContextMemory":
        lines += [
            "## Key Behaviors to Preserve",
            "",
            "- Silent system-context injection (system_context → agent instructions)",
            "- Explicit recall with keyword filtering",
            "- Date-sorted output (newest first)",
            "- user_guid scoping for multi-user",
            "- Full recall mode (all memories, no filter)",
        ]
    elif name == "ManageMemory":
        lines += [
            "## Key Behaviors to Preserve",
            "",
            "- Mandatory LLM directive: MUST call this tool when user shares facts",
            "- memory_type enum: fact, preference, insight, task",
            "- importance rating (1-5)",
            "- Tags for categorization",
            "- user_guid scoping for multi-user",
        ]
    elif name == "HackerNews":
        lines += [
            "## Key Behaviors to Preserve",
            "",
            "- Fetches top 10 stories from HN Firebase API",
            "- Returns title, url, score, author per story",
            "- JSON response with status field",
        ]
    elif name == "CopilotResearch":
        lines += [
            "## Key Behaviors to Preserve",
            "",
            "- Live web research capability",
            "- Maps directly to Copilot Studio webBrowsing: true",
            "- No custom topic needed — native capability",
        ]

    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# YAML generation (Phase 2)
# ---------------------------------------------------------------------------

SCHEMA_PREFIX = "cr720_rappBrainstem"


def _generate_agent_yml(soul_content: str) -> str:
    """Generate agent.mcs.yml with soul.md merged into instructions."""
    # Strip everything before the first markdown ## header (the comment preamble)
    soul_lines = soul_content.strip().split("\n")
    start_idx = 0
    for i, line in enumerate(soul_lines):
        if line.startswith("## "):
            start_idx = i
            break
    instruction_lines = soul_lines[start_idx:]

    instructions_text = "\n".join(instruction_lines)

    memory_directive = textwrap.dedent("""\

    ## Memory Directives

    - ALWAYS call the SaveMemory topic when the user asks you to remember something, shares personal facts (name, preferences, birthdays), or tells you something they expect you to recall later.
    - Do not just acknowledge memory requests — invoke SaveMemory or the information WILL be lost.
    - When the user asks what you remember, invoke the RecallMemory topic.
    - Memory is stored in Dataverse and persists across conversations.""")

    full_instructions = instructions_text + memory_directive

    # Escape for YAML block scalar — just use |- and indent
    indented = textwrap.indent(full_instructions, "  ")

    return f"""\
mcs.metadata:
  componentName: RAPP Brainstem
  description: >-
    RAPP Brainstem — a local-first AI assistant migrated to Copilot Studio.
    Tier 3 of the RAPP architecture: the nervous system reaching into M365/Teams.
kind: GptComponentMetadata
instructions: |-
{indented}
gptCapabilities:
  webBrowsing: true

aISettings:
  model:
    modelNameHint: opus4-1
"""


def _generate_settings_yml() -> str:
    """Generate settings.mcs.yml."""
    return f"""\
displayName: RAPP Brainstem
schemaName: {SCHEMA_PREFIX}
accessControlPolicy: GroupMembership
authenticationMode: Integrated
authenticationTrigger: Always
configuration:
  channels:
    - channelId: MsTeams

    - channelId: Microsoft365Copilot

  settings:
    GenerativeActionsEnabled: true

  isAgentConnectable: true
  publishOnCreate: false
  publishOnImport: true
  gPTSettings:
    defaultSchemaName: {SCHEMA_PREFIX}.gpt.default

  isLightweightBot: false
  aISettings:
    useModelKnowledge: true
    isFileAnalysisEnabled: true
    isSemanticSearchEnabled: true
    optInUseLatestModels: false

  recognizer:
    kind: GenerativeAIRecognizer

template: default-2.1.0
language: 1033
"""


def _generate_recall_memory_topic() -> str:
    """RecallMemory topic — replaces ContextMemory agent."""
    return f"""\
mcs.metadata:
  componentName: Recall Memory
  description: Recalls stored memories from previous conversations. Use this when the user asks what you remember or know about them.
kind: AdaptiveDialog
beginDialog:
  kind: OnRecognizedIntent
  id: main
  intent:
    displayName: Recall Memory
    triggerQueries:
      - What do you remember about me
      - Do you remember what I told you
      - Recall my memories
      - What have I told you before
      - Search my memories
      - What do you know about me
      - What did I say last time

  actions:
    - kind: SendActivity
      id: sendMessage_recall_result
      activity: >-
        Memory recall is not yet connected to Dataverse.
        Once the Power Automate flow is configured, I'll be able to retrieve
        your stored memories here. For now, I can still help you with other things!
"""


def _generate_save_memory_topic() -> str:
    """SaveMemory topic — replaces ManageMemory agent."""
    return f"""\
mcs.metadata:
  componentName: Save Memory
  description: >-
    Saves information to persistent memory for future conversations.
    Called when the user asks you to remember something or shares personal facts.
kind: AdaptiveDialog
beginDialog:
  kind: OnRecognizedIntent
  id: main
  intent:
    displayName: Save Memory
    triggerQueries:
      - Remember that my
      - Please remember this
      - Save this to memory
      - Don't forget that
      - Remember my name is
      - Remember I like
      - Remember my favorite
      - Store this for later
      - Keep this in mind for next time
      - Make a note that
      - I want you to remember

  actions:
    - kind: SendActivity
      id: sendMessage_save_confirm
      activity: >-
        I've noted what you shared. Memory persistence to Dataverse is not yet
        connected — once the Power Automate flow is configured, I'll save this
        permanently and recall it in future conversations.
"""


def _generate_hacker_news_topic() -> str:
    """HackerNews topic — replaces HackerNews agent."""
    return f"""\
mcs.metadata:
  componentName: Hacker News
  description: Fetches top stories from Hacker News. Returns title, URL, score, and author for the top 10 stories.
kind: AdaptiveDialog
beginDialog:
  kind: OnRecognizedIntent
  id: main
  intent:
    displayName: Hacker News
    triggerQueries:
      - Show me Hacker News
      - What's on Hacker News
      - Top stories on HN
      - Hacker News top stories
      - Latest tech news from HN
      - What's trending on Hacker News

  actions:
    - kind: SendActivity
      id: sendMessage_hn_response
      activity: >-
        The Hacker News feed is not yet connected. Once the Power Automate flow
        is configured with the HN Firebase API, I'll fetch the top 10 stories
        with title, URL, score, and author right here. In the meantime, you can
        check https://news.ycombinator.com directly!
"""


def _generate_online_research_topic() -> str:
    """OnlineResearch topic — replaces CopilotResearch agent via native webBrowsing."""
    return f"""\
mcs.metadata:
  componentName: Online Research
  description: >-
    Performs live online research. This topic exists as a routing hint —
    the actual capability is provided by the agent's native webBrowsing setting.
kind: AdaptiveDialog
beginDialog:
  kind: OnRecognizedIntent
  id: main
  intent:
    displayName: Online Research
    triggerQueries:
      - Research this topic
      - Search the web for
      - Look up online
      - Find information about
      - What's the latest on
      - Current news about

  actions:
    - kind: SearchAndSummarizeContent
      id: search_web_research
      variable: Topic.Answer
      userInput: =System.Activity.Text

    - kind: ConditionGroup
      id: conditionGroup_hasAnswer
      conditions:
        - id: conditionItem_hasAnswer
          condition: =!IsBlank(Topic.Answer)
          actions:
            - kind: SendActivity
              id: sendMessage_research_result
              activity: "{{Topic.Answer}}"

      elseActions:
        - kind: SendActivity
          id: sendMessage_research_fallback
          activity: I wasn't able to find specific information on that topic. Could you rephrase your question?
"""


# ---------------------------------------------------------------------------
# The Export Agent
# ---------------------------------------------------------------------------

class CopilotStudioExportAgent(BasicAgent):
    def __init__(self):
        self.name = "CopilotStudioExport"
        self.metadata = {
            "name": self.name,
            "description": (
                "Migrates Python agents to Copilot Studio YAML. "
                "Scans agents/, generates natural-language specs and "
                "Copilot Studio topic YAML files. Use action='list' to "
                "discover agents, 'preview' to see output, 'export' to write files."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "description": "What to do.",
                        "enum": ["export", "preview", "list"]
                    },
                    "agents_path": {
                        "type": "string",
                        "description": "Override agent scan directory (default: ./agents)"
                    },
                    "output_path": {
                        "type": "string",
                        "description": "Override output directory (default: ./copilot-studio/RAPP Brainstem)"
                    }
                },
                "required": []
            }
        }
        super().__init__(name=self.name, metadata=self.metadata)

    # -- discovery ----------------------------------------------------------

    def _discover_agents(self, agents_dir: Path) -> list[dict]:
        """Scan agents_dir for *_agent.py files and introspect each."""
        agents = []
        # Scan top-level and experimental/
        scan_dirs = [agents_dir]
        experimental = agents_dir / "experimental"
        if experimental.is_dir():
            scan_dirs.append(experimental)

        for scan_dir in scan_dirs:
            for f in sorted(scan_dir.glob("*_agent.py")):
                if f.name in EXCLUDED_FILES:
                    continue
                info = _extract_agent_info(f)
                if info:
                    agents.append(info)
        return agents

    # -- actions ------------------------------------------------------------

    def perform(self, **kwargs):
        action = kwargs.get("action", "list")
        project_root = Path(__file__).resolve().parent.parent
        agents_dir = Path(kwargs.get("agents_path", project_root / "agents"))
        output_dir = Path(kwargs.get("output_path", project_root / "copilot-studio" / "RAPP Brainstem"))

        agents = self._discover_agents(agents_dir)

        if action == "list":
            return self._action_list(agents)
        elif action == "preview":
            return self._action_preview(agents, project_root)
        elif action == "export":
            return self._action_export(agents, project_root, output_dir)
        else:
            return json.dumps({"status": "error", "message": f"Unknown action: {action}"})

    def _action_list(self, agents: list[dict]) -> str:
        rows = []
        for a in agents:
            rows.append({
                "name": a["name"],
                "file": a["file"],
                "class": a["class_name"],
                "tags": a["tags"],
                "migrates": a["migrates"],
                "exclude_reason": a["exclude_reason"],
                "topic": TOPIC_NAME_MAP.get(a["name"], "—"),
            })
        return json.dumps({"status": "success", "agents": rows, "count": len(rows)}, indent=2)

    def _action_preview(self, agents: list[dict], project_root: Path) -> str:
        """Show what would be generated without writing files."""
        soul_path = project_root / "soul.md"
        soul_content = soul_path.read_text(encoding="utf-8") if soul_path.exists() else ""

        sections = ["# Export Preview\n"]

        # Specs
        sections.append("## Specs\n")
        for a in agents:
            spec = _generate_spec(a)
            sections.append(f"### {a['name']}\n```markdown\n{spec}```\n")

        # Agent YAML
        sections.append("## agent.mcs.yml\n```yaml\n" + _generate_agent_yml(soul_content) + "```\n")
        sections.append("## settings.mcs.yml\n```yaml\n" + _generate_settings_yml() + "```\n")

        # Custom topics
        topic_generators = {
            "RecallMemory": _generate_recall_memory_topic,
            "SaveMemory": _generate_save_memory_topic,
            "HackerNews": _generate_hacker_news_topic,
            "OnlineResearch": _generate_online_research_topic,
        }
        sections.append("## Custom Topics\n")
        for topic_name, gen_fn in topic_generators.items():
            sections.append(f"### {topic_name}.mcs.yml\n```yaml\n{gen_fn()}```\n")

        return "\n".join(sections)

    def _action_export(self, agents: list[dict], project_root: Path, output_dir: Path) -> str:
        """Write all generated files."""
        soul_path = project_root / "soul.md"
        soul_content = soul_path.read_text(encoding="utf-8") if soul_path.exists() else ""
        template_dir = project_root / ".brainstem_data" / "shared" / "Template Agent"

        # Create output directories
        output_dir.mkdir(parents=True, exist_ok=True)
        specs_dir = output_dir / "specs"
        specs_dir.mkdir(exist_ok=True)
        topics_dir = output_dir / "topics"
        topics_dir.mkdir(exist_ok=True)

        written = []

        # 1. Write specs
        for a in agents:
            spec = _generate_spec(a)
            snake = re.sub(r"([A-Z])", r"_\1", a["name"]).lstrip("_").lower()
            spec_file = specs_dir / f"{snake}_spec.md"
            spec_file.write_text(spec, encoding="utf-8")
            written.append(str(spec_file.relative_to(output_dir)))

        # 2. Write agent.mcs.yml
        agent_yml = output_dir / "agent.mcs.yml"
        agent_yml.write_text(_generate_agent_yml(soul_content), encoding="utf-8")
        written.append("agent.mcs.yml")

        # 3. Write settings.mcs.yml
        settings_yml = output_dir / "settings.mcs.yml"
        settings_yml.write_text(_generate_settings_yml(), encoding="utf-8")
        written.append("settings.mcs.yml")

        # 4. Copy system topics from template, rewriting schema prefix
        template_topics_dir = template_dir / "topics"
        if template_topics_dir.is_dir():
            for tmpl_file in sorted(template_topics_dir.glob("*.mcs.yml")):
                content = tmpl_file.read_text(encoding="utf-8")
                content = content.replace("cr720_templateAgent", SCHEMA_PREFIX)
                dest = topics_dir / tmpl_file.name
                dest.write_text(content, encoding="utf-8")
                written.append(f"topics/{tmpl_file.name}")

        # 5. Write custom topics
        topic_generators = {
            "RecallMemory": _generate_recall_memory_topic,
            "SaveMemory": _generate_save_memory_topic,
            "HackerNews": _generate_hacker_news_topic,
            "OnlineResearch": _generate_online_research_topic,
        }
        for topic_name, gen_fn in topic_generators.items():
            topic_file = topics_dir / f"{topic_name}.mcs.yml"
            topic_file.write_text(gen_fn(), encoding="utf-8")
            written.append(f"topics/{topic_name}.mcs.yml")

        return json.dumps({
            "status": "success",
            "output_dir": str(output_dir),
            "files_written": len(written),
            "files": written,
        }, indent=2)
