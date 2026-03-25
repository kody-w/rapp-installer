"""
CopilotStudio — Unified Copilot Studio agent (export + deploy).

Merges all Copilot Studio capabilities into a single agent file:

  DEPLOY (push = publish, no separate step):
    deploy      — full pipeline: generate YAML → push
    generate    — generate all YAML files without pushing
    push        — push existing YAML to Copilot Studio cloud
    pull        — pull cloud state to local workspace
    changes     — show diff between local and cloud
    install     — install/verify the skills-for-copilot-studio plugin
    status      — check plugin, workspace, and readiness
    list-envs   — list available Power Platform environments
    list-agents — list agents in the target environment

  EXPORT (Python agent introspection):
    scan        — discover Python agents and their classifications
    preview     — show what YAML would be generated without writing
    export      — write migration specs + YAML to workspace

Battle-tested YAML templates with Coalesce() null guards, all
StringPrebuiltEntity, inputType/outputType blocks, and auto-detected
flow GUIDs. OOTB Dataverse Notes (annotation) table — zero custom tables.

Follows the Single File Agent pattern (Constitution Article IV).
"""

import ast
import json
import os
import re
import shutil
import subprocess
import textwrap
from pathlib import Path

from agents.basic_agent import BasicAgent


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_PLUGIN_NAME = "skills-for-copilot-studio"
_PLUGIN_NAMESPACE = "microsoft"
_PLUGIN_CACHE_ROOT = Path.home() / ".claude" / "plugins" / "cache"
_PLUGIN_DIR = _PLUGIN_CACHE_ROOT / _PLUGIN_NAME
_MANAGE_AGENT_GLOB = "copilot-studio/*/scripts/manage-agent.bundle.js"
_DEFAULT_WORKSPACE = "copilot-studio/RAPP Brainstem"
_SCHEMA_PREFIX = "cr720_rappBrainstem"


# ---------------------------------------------------------------------------
# Plugin / CLI helpers
# ---------------------------------------------------------------------------

def _find_manage_agent_script() -> Path | None:
    if not _PLUGIN_DIR.exists():
        return None
    matches = sorted(_PLUGIN_DIR.glob(_MANAGE_AGENT_GLOB), reverse=True)
    return matches[0] if matches else None


def _find_conn_json(workspace: Path) -> dict | None:
    conn_path = workspace / ".mcs" / "conn.json"
    if conn_path.exists():
        return json.loads(conn_path.read_text(encoding="utf-8"))
    template_conn = workspace.parent.parent / ".brainstem_data" / "shared" / \
        "Template Agent" / ".mcs" / "conn.json"
    if template_conn.exists():
        return json.loads(template_conn.read_text(encoding="utf-8"))
    return None


def _build_env_args(conn: dict) -> list[str]:
    args = []
    account = conn.get("AccountInfo", {})
    if account.get("TenantId"):
        args += ["--tenant-id", account["TenantId"]]
    if conn.get("EnvironmentId"):
        args += ["--environment-id", conn["EnvironmentId"]]
    if conn.get("DataverseEndpoint"):
        args += ["--environment-url", conn["DataverseEndpoint"]]
    if conn.get("AgentManagementEndpoint"):
        args += ["--agent-mgmt-url", conn["AgentManagementEndpoint"]]
    return args


def _run_manage_agent(cmd: str, extra_args: list[str] = None,
                      timeout: int = 180) -> dict:
    script = _find_manage_agent_script()
    if not script:
        return {
            "status": "error",
            "error": "manage-agent.bundle.js not found. Run with action='install' first."
        }
    full_cmd = ["node", str(script), cmd] + (extra_args or [])
    try:
        result = subprocess.run(
            full_cmd, capture_output=True, text=True, timeout=timeout
        )
        output = result.stdout.strip()
        stderr = result.stderr.strip()
        if output:
            try:
                return json.loads(output)
            except json.JSONDecodeError:
                return {
                    "status": "success" if result.returncode == 0 else "error",
                    "output": output, "stderr": stderr,
                }
        if result.returncode != 0:
            return {"status": "error", "error": stderr or f"Exit code {result.returncode}"}
        return {"status": "success", "output": stderr or "(no output)"}
    except subprocess.TimeoutExpired:
        return {"status": "error", "error": f"Timed out after {timeout}s"}
    except FileNotFoundError:
        return {"status": "error", "error": "Node.js not found on PATH"}
    except Exception as e:
        return {"status": "error", "error": str(e)}


# ---------------------------------------------------------------------------
# Plugin installation
# ---------------------------------------------------------------------------

def _install_plugin() -> dict:
    existing = _find_manage_agent_script()
    if existing:
        return {"status": "success", "message": "Plugin already installed.",
                "manage_agent_path": str(existing)}
    _PLUGIN_CACHE_ROOT.mkdir(parents=True, exist_ok=True)
    for method in [_install_via_claude_cli, _install_via_npm]:
        result = method()
        if result.get("status") == "success":
            return result
    return {
        "status": "error",
        "error": (
            "Could not auto-install. Manual steps:\n"
            "1. /plugin marketplace add microsoft/skills-for-copilot-studio\n"
            "2. /plugin install copilot-studio@skills-for-copilot-studio"
        ),
    }


def _install_via_claude_cli() -> dict:
    try:
        subprocess.run(
            ["claude", "plugin", "marketplace", "add",
             f"{_PLUGIN_NAMESPACE}/{_PLUGIN_NAME}"],
            capture_output=True, text=True, timeout=60)
        subprocess.run(
            ["claude", "plugin", "install",
             f"copilot-studio@{_PLUGIN_NAME}"],
            capture_output=True, text=True, timeout=120)
        script = _find_manage_agent_script()
        if script:
            return {"status": "success", "message": "Installed via Claude CLI.",
                    "manage_agent_path": str(script)}
        return {"status": "error", "error": "CLI ran but script not found"}
    except Exception as e:
        return {"status": "error", "error": str(e)}


def _install_via_npm() -> dict:
    try:
        subprocess.run(
            ["npm", "install", "--prefix", str(_PLUGIN_DIR),
             f"@{_PLUGIN_NAMESPACE}/{_PLUGIN_NAME}"],
            capture_output=True, text=True, timeout=120)
        script = _find_manage_agent_script()
        if script:
            return {"status": "success", "message": "Installed via npm.",
                    "manage_agent_path": str(script)}
        return {"status": "error", "error": "npm ran but script not found"}
    except Exception as e:
        return {"status": "error", "error": str(e)}


# ---------------------------------------------------------------------------
# YAML generation — battle-tested templates from production deployment
#
# Key lessons learned:
#   1. ALL inputs must be StringPrebuiltEntity (not Number/Boolean)
#   2. ALL flow bindings must use Coalesce() with non-null defaults
#   3. inputType/outputType blocks are REQUIRED for Topic.* Power Fx vars
#   4. Flow inputs use generic keys (text, text_1, text_2) not friendly names
#   5. Flow output key is always "output"
#   6. flowId must be the GUID assigned by the portal, not a logical name
#   7. Do NOT create CloudFlowDefinition .mcs.yml stubs — they cause errors
#   8. Push = Publish (no separate publish step via LSP)
# ---------------------------------------------------------------------------

def _generate_agent_yml(soul_path: Path) -> str:
    soul_content = ""
    if soul_path.exists():
        lines = soul_path.read_text(encoding="utf-8").strip().split("\n")
        start = next((i for i, l in enumerate(lines) if l.startswith("## ")), 0)
        soul_content = "\n".join(lines[start:])

    memory_directive = textwrap.dedent("""\

    ## Memory Directives

    - ALWAYS call the SaveMemory topic when the user asks you to remember something, shares personal facts (name, preferences, birthdays), or tells you something they expect you to recall later.
    - Do not just acknowledge memory requests — invoke SaveMemory or the information WILL be lost.
    - When the user asks what you remember, invoke the RecallMemory topic.
    - Memory is stored in the OOTB Dataverse Notes (annotation) table and persists across conversations. No custom tables required.
    - The SaveMemory topic accepts: memory_type (fact/preference/insight/task), content, importance (1-5).
    - The RecallMemory topic accepts: keywords and full_recall (true/false).
    - Memories are scoped per user via the Note's createdby field.""")

    full_instructions = soul_content + memory_directive
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
    return f"""\
displayName: RAPP Brainstem
schemaName: {_SCHEMA_PREFIX}
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
  publishOnImport: true
  gPTSettings:
    defaultSchemaName: {_SCHEMA_PREFIX}.gpt.default
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


def _generate_save_memory_topic(flow_id: str = "") -> str:
    """SaveMemory topic — mirrors ManageMemoryAgent.

    Flow inputs (all strings): text=memoryType, text_1=content, text_2=importance
    Flow output: output (confirmation message)
    All bindings use Coalesce() to prevent null → TriggerInputSchemaMismatch.
    """
    flow_line = f"      flowId: {flow_id}" if flow_id else "      flowId: REPLACE_WITH_FLOW_GUID"
    return f"""\
mcs.metadata:
  componentName: Save Memory
  description: Saves information to persistent memory for future conversations. Called when the user asks you to remember something or shares personal facts.
kind: AdaptiveDialog
inputs:
  - kind: AutomaticTaskInput
    propertyName: MemoryType
    description: "The category of memory to store. Must be one of: fact, preference, insight, or task. Default to fact if unclear."
    entity: StringPrebuiltEntity
    shouldPromptUser: false
    defaultValue: ="fact"

  - kind: AutomaticTaskInput
    propertyName: Content
    description: The actual memory text to store, extracted from what the user said. Always extract something to store.
    entity: StringPrebuiltEntity
    shouldPromptUser: true

  - kind: AutomaticTaskInput
    propertyName: Importance
    description: How important this memory is as a string from 1-5. Default to 3 if not specified.
    entity: StringPrebuiltEntity
    shouldPromptUser: false
    defaultValue: ="3"

modelDescription: Use this when the user asks you to remember something, shares personal facts (name, preferences, birthdays), or tells you something they expect recalled later. Extract memory_type (fact, preference, insight, or task), content, and importance (1-5) from the user's message. Always provide a value for all three fields.
beginDialog:
  kind: OnRecognizedIntent
  id: main
  intent:
    displayName: Save Memory
    includeInOnSelectIntent: false
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
    - kind: InvokeFlowAction
      id: invokeFlowAction_7589o3
{flow_line}
      input:
        binding:
          text: =Coalesce(Topic.MemoryType, "fact")
          text_1: =Coalesce(Topic.Content, "No content provided")
          text_2: =Coalesce(Topic.Importance, "3")
      output:
        binding:
          output: Topic.ConfirmationMessage

    - kind: ConditionGroup
      id: conditionGroup_hasConfirm3p
      conditions:
        - id: conditionItem_hasConfirm8w
          condition: =!IsBlank(Topic.ConfirmationMessage)
          actions:
            - kind: SendActivity
              id: sendMessage_confirmOk5v
              activity: "{{Topic.ConfirmationMessage}}"

      elseActions:
        - kind: SendActivity
          id: sendMessage_fallbackErr2m
          activity: I tried to save that memory but something went wrong. Please try again.

    - kind: CancelAllDialogs
      id: cancelAllDialogs_sm01

inputType:
  properties:
    MemoryType:
      displayName: MemoryType
      description: "The category of memory: fact, preference, insight, or task."
      type: String

    Content:
      displayName: Content
      description: The memory text to store.
      type: String

    Importance:
      displayName: Importance
      description: Importance level from 1-5 as text. Defaults to 3.
      type: String

outputType:
  properties:
    ConfirmationMessage:
      displayName: ConfirmationMessage
      description: Confirmation message returned by the flow.
      type: String
"""


def _generate_recall_memory_topic(flow_id: str = "") -> str:
    """RecallMemory topic — mirrors ContextMemoryAgent.

    Flow inputs (all strings): text=keywords, text_1=fullRecall
    Flow output: output (formatted memories)
    All bindings use Coalesce() to prevent null → TriggerInputSchemaMismatch.
    """
    flow_line = f"      flowId: {flow_id}" if flow_id else "      flowId: REPLACE_WITH_FLOW_GUID"
    return f"""\
mcs.metadata:
  componentName: Recall Memory
  description: Recalls stored memories from previous conversations. Use this when the user asks what you remember or know about them.
kind: AdaptiveDialog
inputs:
  - kind: AutomaticTaskInput
    propertyName: Keywords
    description: Optional comma-separated keywords to filter memories by topic or subject. Always provide at least an empty value.
    entity: StringPrebuiltEntity
    shouldPromptUser: false
    defaultValue: =" "

  - kind: AutomaticTaskInput
    propertyName: FullRecall
    description: Set to true to return all memories without filtering. Set to true when the user does not specify a particular topic or keyword to search for.
    entity: StringPrebuiltEntity
    shouldPromptUser: false
    defaultValue: ="true"

modelDescription: Use this when the user asks what you remember about them, wants to recall past conversations, or asks you to search stored memories. Always set Keywords to a space if no keywords are specified. Set FullRecall to true if no specific filter is needed.
beginDialog:
  kind: OnRecognizedIntent
  id: main
  intent:
    displayName: Recall Memory
    includeInOnSelectIntent: false
    triggerQueries:
      - What do you remember about me
      - Do you remember what I told you
      - Recall my memories
      - What have I told you before
      - Search my memories
      - What do you know about me
      - What did I say last time

  actions:
    - kind: InvokeFlowAction
      id: invokeFlowAction_TvDUTq
{flow_line}
      input:
        binding:
          text: =Coalesce(Topic.Keywords, " ")
          text_1: =Coalesce(Topic.FullRecall, "true")
      output:
        binding:
          output: Topic.FormattedMemories

    - kind: ConditionGroup
      id: conditionGroup_hasMemR3
      conditions:
        - id: conditionItem_hasMemR3
          condition: =!IsBlank(Topic.FormattedMemories)
          actions:
            - kind: SendActivity
              id: sendMessage_recallRes
              activity: "{{Topic.FormattedMemories}}"

      elseActions:
        - kind: SendActivity
          id: sendMessage_noMemory
          activity: I do not have any stored memories matching your request. If you would like me to remember something, just tell me and I will save it for future conversations.

    - kind: CancelAllDialogs
      id: cancelAllDialogs_rm01

inputType:
  properties:
    Keywords:
      displayName: Keywords
      description: Comma-separated keywords to filter memories.
      type: String

    FullRecall:
      displayName: FullRecall
      description: Set to true to return all memories without filtering.
      type: String

outputType:
  properties:
    FormattedMemories:
      displayName: FormattedMemories
      description: Formatted memory text returned by the flow.
      type: String
"""


def _generate_hacker_news_topic() -> str:
    """HackerNews topic — uses web browsing (no Power Automate flow needed)."""
    return """\
mcs.metadata:
  componentName: Hacker News
  description: Fetches and displays top stories from Hacker News using the agent's web browsing capability.
kind: AdaptiveDialog
modelDescription: Use this when the user asks about Hacker News, top tech stories, HN, or trending tech news. Browse https://news.ycombinator.com and list the top 10 stories with title, URL, score, and author.
beginDialog:
  kind: OnRecognizedIntent
  id: main
  intent:
    displayName: Hacker News
    includeInOnSelectIntent: false
    triggerQueries:
      - Show me Hacker News
      - What is trending on Hacker News
      - Top stories on HN
      - Get Hacker News front page
      - Show me the top posts on Hacker News
      - What is on Hacker News right now
      - Latest Hacker News stories
      - HN top 10
  actions:
    - kind: SearchAndSummarizeContent
      id: searchWeb_hn
      variable: Topic.HNStories
      userInput: top 10 stories from Hacker News https://news.ycombinator.com with title, URL, score, and author
      autoSend: false

    - kind: ConditionGroup
      id: conditionGroup_hasStories
      conditions:
        - id: conditionItem_hasStories
          condition: =!IsBlank(Topic.HNStories)
          actions:
            - kind: SendActivity
              id: sendMessage_hn_result
              activity: "{Topic.HNStories}"
      elseActions:
        - kind: SendActivity
          id: sendMessage_hn_fallback
          activity: I wasn't able to fetch Hacker News stories right now. You can check https://news.ycombinator.com directly.

    - kind: CancelAllDialogs
      id: cancelAllDialogs_hn01
"""


def _detect_flow_ids(workspace: Path) -> dict:
    """Detect portal-assigned flow GUIDs from workflow folders."""
    flow_ids = {}
    workflows_dir = workspace / "workflows"
    if not workflows_dir.exists():
        return flow_ids
    for folder in workflows_dir.iterdir():
        if not folder.is_dir():
            continue
        meta_file = folder / "metadata.yml"
        if meta_file.exists():
            content = meta_file.read_text(encoding="utf-8")
            for line in content.split("\n"):
                if line.startswith("workflowId:"):
                    wf_id = line.split(":", 1)[1].strip()
                if line.startswith("name:"):
                    wf_name = line.split(":", 1)[1].strip()
            if "Store" in folder.name or "Save" in folder.name:
                flow_ids["save"] = wf_id
            elif "Recall" in folder.name:
                flow_ids["recall"] = wf_id
    return flow_ids


def _generate_all(project_root: Path, workspace: Path) -> dict:
    """Generate all Copilot Studio YAML files.

    Detects existing flow GUIDs from portal-created workflow folders
    and wires them into the topic YAML automatically.
    """
    workspace.mkdir(parents=True, exist_ok=True)
    topics_dir = workspace / "topics"
    topics_dir.mkdir(exist_ok=True)

    written = []

    # Detect flow IDs from existing workflow folders
    flow_ids = _detect_flow_ids(workspace)
    save_flow_id = flow_ids.get("save", "")
    recall_flow_id = flow_ids.get("recall", "")

    # --- agent.mcs.yml (only if not pulled from server) ---
    agent_yml = workspace / "agent.mcs.yml"
    agent_content = agent_yml.read_text(encoding="utf-8").strip() if agent_yml.exists() else ""
    if not agent_content or agent_content == "{}":
        soul_path = project_root / "soul.md"
        agent_yml.write_text(_generate_agent_yml(soul_path), encoding="utf-8")
        written.append("agent.mcs.yml (generated)")
    else:
        written.append("agent.mcs.yml (preserved)")

    # --- settings.mcs.yml (preserve pulled version) ---
    settings_path = workspace / "settings.mcs.yml"
    if not settings_path.exists():
        settings_path.write_text(_generate_settings_yml(), encoding="utf-8")
        written.append("settings.mcs.yml (generated)")
    else:
        written.append("settings.mcs.yml (preserved)")

    # --- System topics from template ---
    template_topics = project_root / ".brainstem_data" / "shared" / \
        "Template Agent" / "topics"
    if template_topics.is_dir():
        for tmpl in sorted(template_topics.glob("*.mcs.yml")):
            base_name = tmpl.name.replace(".mcs.yml", "")
            if base_name in ("SaveMemory", "RecallMemory", "HackerNews"):
                continue
            dest = topics_dir / f"{_SCHEMA_PREFIX}.topic.{base_name}.mcs.yml"
            if not dest.exists():
                content = tmpl.read_text(encoding="utf-8")
                content = content.replace("cr720_templateAgent", _SCHEMA_PREFIX)
                dest.write_text(content, encoding="utf-8")
                written.append(f"topics/{dest.name}")

    # --- SaveMemory topic ---
    save_topic = topics_dir / f"{_SCHEMA_PREFIX}.topic.SaveMemory.mcs.yml"
    save_topic.write_text(_generate_save_memory_topic(save_flow_id), encoding="utf-8")
    written.append(f"topics/{save_topic.name} (flowId: {save_flow_id or 'NEEDS_FLOW'})")

    # --- RecallMemory topic ---
    recall_topic = topics_dir / f"{_SCHEMA_PREFIX}.topic.RecallMemory.mcs.yml"
    recall_topic.write_text(_generate_recall_memory_topic(recall_flow_id), encoding="utf-8")
    written.append(f"topics/{recall_topic.name} (flowId: {recall_flow_id or 'NEEDS_FLOW'})")

    # --- HackerNews topic (web browsing, no flow needed) ---
    hn_topic = topics_dir / f"{_SCHEMA_PREFIX}.topic.HackerNews.mcs.yml"
    hn_topic.write_text(_generate_hacker_news_topic(), encoding="utf-8")
    written.append(f"topics/{hn_topic.name}")

    # --- Clean up stale CloudFlowDefinition stubs ---
    workflows_dir = workspace / "workflows"
    if workflows_dir.exists():
        for stale in workflows_dir.glob("*.mcs.yml"):
            stale.unlink()
            written.append(f"DELETED stale stub: workflows/{stale.name}")

    result = {
        "status": "success",
        "output_dir": str(workspace),
        "files_written": len(written),
        "files": written,
        "flow_ids_detected": flow_ids,
    }

    if not save_flow_id or not recall_flow_id:
        result["next_step"] = (
            "Flow GUIDs not detected. After first push, create the flows in "
            "Copilot Studio portal, then pull + generate again to wire them."
        )

    return result


# ---------------------------------------------------------------------------
# Agent introspection (scan/preview/export from Python agents)
# ---------------------------------------------------------------------------

_EXCLUDED_FILES = {"basic_agent.py", "copilot_studio_agent.py"}

_TOPIC_NAME_MAP = {
    "ContextMemory": "RecallMemory",
    "ManageMemory": "SaveMemory",
    "HackerNews": "HackerNews",
    "CopilotResearch": "OnlineResearch",
}


def _classify_source(source: str) -> list[str]:
    tags = []
    if "AzureFileStorageManager" in source:
        tags.append("memory")
    if any(t in source for t in ("requests.get", "requests.post", "urllib.request")):
        tags.append("api")
    if "subprocess" in source:
        tags.append("cli")
    if "importlib" in source or "spec_from_file_location" in source:
        tags.append("meta")
    if "def system_context" in source and "return None" not in source.split("def system_context")[1].split("def ")[0]:
        tags.append("context")
    return tags or ["generic"]


def _extract_agent_info(file_path: Path) -> dict | None:
    source = file_path.read_text(encoding="utf-8")
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None

    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        if not any(
            (isinstance(b, ast.Name) and b.id == "BasicAgent") or
            (isinstance(b, ast.Attribute) and b.attr == "BasicAgent")
            for b in node.bases
        ):
            continue

        info = {"class_name": node.name, "file": file_path.name,
                "source": source, "tags": _classify_source(source)}

        for item in ast.walk(node):
            if isinstance(item, ast.Assign):
                for target in item.targets:
                    if isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name):
                        if target.value.id == "self" and target.attr == "name" and isinstance(item.value, ast.Constant):
                            info["name"] = item.value.value
                        if target.value.id == "self" and target.attr == "metadata" and isinstance(item.value, ast.Dict):
                            try:
                                meta_src = ast.get_source_segment(source, item.value)
                                if meta_src:
                                    meta_src = meta_src.replace("self.name", repr(info.get("name", "Unknown")))
                                    info["metadata"] = ast.literal_eval(meta_src)
                            except Exception:
                                pass

        if "name" not in info:
            info["name"] = node.name.replace("Agent", "")
        if "metadata" not in info:
            info["metadata"] = {"name": info["name"], "description": "", "parameters": {"type": "object", "properties": {}}}

        migrates = "meta" not in info["tags"] and info["name"] != "LearnNew"
        info["migrates"] = migrates
        info["exclude_reason"] = "" if migrates else "Meta-agent — no Copilot Studio equivalent"
        return info
    return None


def _discover_agents(agents_dir: Path) -> list[dict]:
    agents = []
    scan_dirs = [agents_dir]
    experimental = agents_dir / "experimental"
    if experimental.is_dir():
        scan_dirs.append(experimental)
    for scan_dir in scan_dirs:
        for f in sorted(scan_dir.glob("*_agent.py")):
            if f.name in _EXCLUDED_FILES:
                continue
            info = _extract_agent_info(f)
            if info:
                agents.append(info)
    return agents


def _generate_spec(info: dict) -> str:
    meta = info["metadata"]
    name = info["name"]
    desc = meta.get("description", "No description.")
    params = meta.get("parameters", {}).get("properties", {})
    required = meta.get("parameters", {}).get("required", [])
    tags = info["tags"]

    lines = [
        f"# {name} Agent — Migration Spec", "",
        f"**Source:** `{info['file']}`  ",
        f"**Classification:** {', '.join(tags)}  ",
        f"**Migrates:** {'Yes' if info['migrates'] else 'No — ' + info['exclude_reason']}",
        "", "## Purpose", "", desc, "",
    ]
    if params:
        lines += ["## Parameters", ""]
        for pname, pdef in params.items():
            req = " *(required)*" if pname in required else ""
            enum_vals = pdef.get("enum")
            enum_str = f" — one of: {', '.join(f'`{v}`' for v in enum_vals)}" if enum_vals else ""
            lines.append(f"- **`{pname}`** (`{pdef.get('type', 'string')}`){req}: {pdef.get('description', '')}{enum_str}")
        lines.append("")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# The Agent
# ---------------------------------------------------------------------------

class CopilotStudioAgent(BasicAgent):
    def __init__(self):
        self.name = "CopilotStudio"
        self.metadata = {
            "name": self.name,
            "description": (
                "Unified Copilot Studio agent: deploy, export, and test. "
                "Generates YAML, pushes to cloud (push=publish), scans Python "
                "agents for migration, runs Playwright tests. "
                "Use action='deploy' for one-shot generate+push."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "description": "Operation to perform.",
                        "enum": [
                            "deploy", "generate", "push", "pull", "status",
                            "install", "changes", "list-envs", "list-agents",
                            "scan", "preview", "export"
                        ]
                    },
                    "workspace": {
                        "type": "string",
                        "description": (
                            "Path to the Copilot Studio agent folder "
                            "(default: ./copilot-studio/RAPP Brainstem)"
                        )
                    },
                    "tenant_id": {
                        "type": "string",
                        "description": "Azure AD tenant ID (auto-detected from conn.json)"
                    },
                    "environment_id": {
                        "type": "string",
                        "description": "Power Platform environment ID (auto-detected)"
                    },
                },
                "required": []
            }
        }
        super().__init__(name=self.name, metadata=self.metadata)

    def perform(self, **kwargs):
        action = kwargs.get("action", "status")
        project_root = Path(__file__).resolve().parent.parent
        workspace = Path(kwargs.get("workspace",
                                    project_root / _DEFAULT_WORKSPACE))

        handlers = {
            # Deploy
            "deploy": self._do_deploy,
            "generate": self._do_generate,
            "push": self._do_push,
            "pull": self._do_pull,
            "status": self._do_status,
            "install": self._do_install,
            "changes": self._do_changes,
            "list-envs": self._do_list_envs,
            "list-agents": self._do_list_agents,
            # Export
            "scan": self._do_scan,
            "preview": self._do_preview,
            "export": self._do_export,
        }
        handler = handlers.get(action)
        if not handler:
            return json.dumps({"status": "error", "error": f"Unknown action: {action}"})
        return handler(project_root=project_root, workspace=workspace, **kwargs)

    def _do_deploy(self, **kwargs) -> str:
        project_root, workspace = kwargs["project_root"], kwargs["workspace"]
        steps = []

        # Step 1: Plugin
        if not _find_manage_agent_script():
            r = _install_plugin()
            steps.append({"step": "install", "result": r})
            if r.get("status") != "success":
                return json.dumps({"status": "error", "steps": steps}, indent=2)

        # Step 2: Generate
        gen = _generate_all(project_root, workspace)
        steps.append({"step": "generate", "result": gen})
        if gen.get("status") != "success":
            return json.dumps({"status": "error", "steps": steps}, indent=2)

        # Step 3: Push
        conn = self._resolve_conn(workspace, kwargs)
        if not conn:
            steps.append({"step": "push", "result": {
                "status": "skipped",
                "reason": "No conn.json. Clone an agent first or provide tenant_id/environment_id."
            }})
            return json.dumps({"status": "partial", "steps": steps}, indent=2)

        push_args = ["--workspace", str(workspace)] + _build_env_args(conn)
        push = _run_manage_agent("push", push_args, timeout=300)
        steps.append({"step": "push", "result": push})

        ok = push.get("status") == "success" or (
            isinstance(push.get("result"), dict) and push["result"].get("code") == 200
        )
        return json.dumps({
            "status": "success" if ok else "error",
            "message": "Deploy complete. Push = Publish." if ok else "Push failed.",
            "steps": steps,
        }, indent=2)

    def _do_generate(self, **kwargs) -> str:
        return json.dumps(
            _generate_all(kwargs["project_root"], kwargs["workspace"]), indent=2)

    def _do_push(self, **kwargs) -> str:
        workspace = kwargs["workspace"]
        if not (workspace / "agent.mcs.yml").exists():
            return json.dumps({"status": "error",
                               "error": "No agent.mcs.yml. Run action='generate' first."})
        conn = self._resolve_conn(workspace, kwargs)
        args = ["--workspace", str(workspace)]
        if conn:
            args += _build_env_args(conn)
        return json.dumps(_run_manage_agent("push", args, timeout=300), indent=2)

    def _do_pull(self, **kwargs) -> str:
        workspace = kwargs["workspace"]
        conn = self._resolve_conn(workspace, kwargs)
        args = ["--workspace", str(workspace)]
        if conn:
            args += _build_env_args(conn)
        return json.dumps(_run_manage_agent("pull", args, timeout=300), indent=2)

    def _do_status(self, **kwargs) -> str:
        workspace = kwargs["workspace"]
        script = _find_manage_agent_script()
        agent_yml = workspace / "agent.mcs.yml"
        conn = _find_conn_json(workspace) if agent_yml.exists() else None
        flow_ids = _detect_flow_ids(workspace)
        topics_dir = workspace / "topics"

        status = {
            "status": "success",
            "plugin_installed": script is not None,
            "workspace_exists": agent_yml.exists(),
            "connection_info": conn is not None,
            "flow_ids": flow_ids,
            "topic_count": len(list(topics_dir.glob("*.mcs.yml"))) if topics_dir.exists() else 0,
            "ready_to_deploy": all([
                script, agent_yml.exists(), conn,
                flow_ids.get("save"), flow_ids.get("recall")
            ]),
        }
        if conn:
            status["environment_id"] = conn.get("EnvironmentId", "")
        return json.dumps(status, indent=2)

    def _do_install(self, **kwargs) -> str:
        return json.dumps(_install_plugin(), indent=2)

    def _do_changes(self, **kwargs) -> str:
        workspace = kwargs["workspace"]
        conn = self._resolve_conn(workspace, kwargs)
        args = ["--workspace", str(workspace)]
        if conn:
            args += _build_env_args(conn)
        return json.dumps(_run_manage_agent("changes", args), indent=2)

    def _do_list_envs(self, **kwargs) -> str:
        conn = self._resolve_conn(kwargs["workspace"], kwargs)
        if not conn or not conn.get("AccountInfo", {}).get("TenantId"):
            return json.dumps({"status": "error", "error": "tenant_id required."})
        return json.dumps(_run_manage_agent("list-envs", _build_env_args(conn)), indent=2)

    def _do_list_agents(self, **kwargs) -> str:
        conn = self._resolve_conn(kwargs["workspace"], kwargs)
        if not conn or not conn.get("EnvironmentId"):
            return json.dumps({"status": "error", "error": "environment_id required."})
        return json.dumps(_run_manage_agent("list-agents", _build_env_args(conn)), indent=2)

    # -- scan (discover Python agents) ------------------------------------

    def _do_scan(self, **kwargs) -> str:
        project_root = kwargs["project_root"]
        agents_dir = project_root / "agents"
        agents = _discover_agents(agents_dir)
        rows = []
        for a in agents:
            rows.append({
                "name": a["name"], "file": a["file"],
                "class": a["class_name"], "tags": a["tags"],
                "migrates": a["migrates"],
                "exclude_reason": a["exclude_reason"],
                "topic": _TOPIC_NAME_MAP.get(a["name"], "—"),
            })
        return json.dumps({"status": "success", "agents": rows, "count": len(rows)}, indent=2)

    # -- preview (show what would be generated) ----------------------------

    def _do_preview(self, **kwargs) -> str:
        project_root = kwargs["project_root"]
        agents = _discover_agents(project_root / "agents")
        sections = ["# Export Preview\n"]
        sections.append("## Agent Specs\n")
        for a in agents:
            sections.append(f"### {a['name']}\n```markdown\n{_generate_spec(a)}```\n")
        return "\n".join(sections)

    # -- export (write migration specs) ------------------------------------

    def _do_export(self, **kwargs) -> str:
        project_root = kwargs["project_root"]
        workspace = kwargs["workspace"]
        agents = _discover_agents(project_root / "agents")
        specs_dir = workspace / "specs"
        specs_dir.mkdir(parents=True, exist_ok=True)
        written = []
        for a in agents:
            spec = _generate_spec(a)
            snake = re.sub(r"([A-Z])", r"_\1", a["name"]).lstrip("_").lower()
            spec_file = specs_dir / f"{snake}_spec.md"
            spec_file.write_text(spec, encoding="utf-8")
            written.append(str(spec_file.relative_to(workspace)))
        # Also run generate to create the YAML
        gen_result = _generate_all(project_root, workspace)
        return json.dumps({
            "status": "success",
            "specs_written": written,
            "yaml_result": gen_result,
        }, indent=2)

    # -- helpers ------------------------------------------------------------

    def _resolve_conn(self, workspace: Path, kwargs: dict) -> dict | None:
        conn = _find_conn_json(workspace)
        if kwargs.get("tenant_id"):
            if not conn:
                conn = {"AccountInfo": {}}
            conn.setdefault("AccountInfo", {})["TenantId"] = kwargs["tenant_id"]
        if kwargs.get("environment_id"):
            if not conn:
                conn = {"AccountInfo": {}}
            conn["EnvironmentId"] = kwargs["environment_id"]
        return conn
