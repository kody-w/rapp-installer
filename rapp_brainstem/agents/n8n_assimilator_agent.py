"""
n8n Workflow Assimilator — Borg meets Transpiler.

Point this agent at an n8n workflow JSON on GitHub and it will:
1. ASSIMILATE — fetch and analyze the workflow (nodes, connections, triggers)
2. GENERATE  — produce a brainstem-compatible agent.py
3. TRANSPILE — convert the agent.py to a Copilot Studio solution
4. DEPLOY    — push to Power Platform via pac CLI

"Your workflow's distinctiveness will be added to our own."

Usage: "Assimilate this n8n workflow https://github.com/owner/repo/blob/main/flow.json"
"""

import ast
import json
import os
import re
import shutil
import subprocess
import textwrap
import urllib.error
import urllib.request
from datetime import datetime, timezone

try:
    from agents.basic_agent import BasicAgent
except ModuleNotFoundError:
    from basic_agent import BasicAgent


# ---------------------------------------------------------------------------
# GitHub URL parsing
# ---------------------------------------------------------------------------

_GITHUB_BLOB_RE = re.compile(
    r"https?://github\.com/([^/]+)/([^/]+)/blob/([^/]+)/(.+)"
)
_GITHUB_RAW_RE = re.compile(
    r"https?://raw\.githubusercontent\.com/([^/]+)/([^/]+)/([^/]+)/(.+)"
)
_GITHUB_API_RE = re.compile(
    r"https?://api\.github\.com/repos/([^/]+)/([^/]+)/contents/(.+)"
)


def _parse_github_url(url):
    """Extract owner, repo, branch, path from a GitHub URL.

    Returns dict with keys owner/repo/branch/path, or None if not a GitHub URL.
    """
    for pattern in (_GITHUB_BLOB_RE, _GITHUB_RAW_RE):
        m = pattern.match(url)
        if m:
            return {
                "owner": m.group(1),
                "repo": m.group(2),
                "branch": m.group(3),
                "path": m.group(4),
            }
    m = _GITHUB_API_RE.match(url)
    if m:
        return {
            "owner": m.group(1),
            "repo": m.group(2),
            "branch": "main",
            "path": m.group(3),
        }
    return None


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------


def _fetch_json_url(url, token=None, timeout=30):
    """Fetch a URL and return parsed JSON."""
    req = urllib.request.Request(url)
    req.add_header("User-Agent", "N8nAssimilator/1.0")
    if token:
        req.add_header("Authorization", f"token {token}")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
        if len(raw) > 1_048_576:  # 1 MB guard
            raise ValueError("Workflow file exceeds 1 MB size limit")
        return json.loads(raw.decode("utf-8"))


def _fetch_raw_text(url, token=None, timeout=30):
    """Fetch a URL and return raw text."""
    req = urllib.request.Request(url)
    req.add_header("User-Agent", "N8nAssimilator/1.0")
    if token:
        req.add_header("Authorization", f"token {token}")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
        if len(raw) > 1_048_576:
            raise ValueError("Workflow file exceeds 1 MB size limit")
        return raw.decode("utf-8")


# ---------------------------------------------------------------------------
# n8n node type classification
# ---------------------------------------------------------------------------

_TRIGGER_TYPES = {
    "webhook", "manualTrigger", "cron", "scheduleTrigger",
    "emailTrigger", "httpRequestTrigger",
}

_NODE_TYPE_SHORT = re.compile(r"(?:n8n-nodes-base\.|@n8n/n8n-nodes-[^.]+\.)(.+)")


def _short_type(full_type):
    """Extract short node type from full n8n type string."""
    m = _NODE_TYPE_SHORT.match(full_type)
    return m.group(1) if m else full_type


# ---------------------------------------------------------------------------
# Name utilities
# ---------------------------------------------------------------------------


def _to_pascal(name):
    """Convert a string to PascalCase."""
    cleaned = re.sub(r"[^a-zA-Z0-9\s_-]", "", name)
    words = re.split(r"[\s_-]+", cleaned)
    return "".join(w.capitalize() for w in words if w)


def _to_snake(name):
    """Convert a string to snake_case."""
    s = re.sub(r"[^a-zA-Z0-9]", " ", name).strip()
    s = re.sub(r"\s+", "_", s)
    s = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s)
    return s.lower()


# ===================================================================
# Agent
# ===================================================================


class N8nAssimilatorAgent(BasicAgent):
    def __init__(self):
        self.name = "N8nAssimilator"
        self.metadata = {
            "name": self.name,
            "description": (
                "Assimilates n8n workflow JSON files from GitHub into brainstem agents, "
                "then transpiles them to Copilot Studio solutions and deploys via pac CLI. "
                "Actions: assimilate (fetch & analyze), generate (create agent.py), "
                "transpile (Copilot Studio solution), deploy (pac CLI push), "
                "pipeline (all stages), history (past runs). "
                "Give it a GitHub URL to an n8n .json file to begin."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": [
                            "assimilate",
                            "generate",
                            "transpile",
                            "deploy",
                            "pipeline",
                            "history",
                        ],
                        "description": "Pipeline stage to run.",
                    },
                    "url": {
                        "type": "string",
                        "description": "GitHub URL to an n8n workflow .json file.",
                    },
                    "agent_name": {
                        "type": "string",
                        "description": "Optional name for the generated agent.",
                    },
                    "agent_file": {
                        "type": "string",
                        "description": "Path to an existing agent.py (for transpile/deploy).",
                    },
                    "output_dir": {
                        "type": "string",
                        "description": "Optional output directory override.",
                    },
                    "environment_url": {
                        "type": "string",
                        "description": "Dataverse environment URL for deployment.",
                    },
                    "tenant_id": {
                        "type": "string",
                        "description": "Azure tenant ID for deployment.",
                    },
                    "dry_run": {
                        "type": "boolean",
                        "description": "Preview only — do not write files or deploy.",
                    },
                },
                "required": ["action"],
            },
        }
        self._base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self._data_dir = os.path.join(
            self._base_dir, ".brainstem_data", "n8n_assimilator"
        )
        self._agents_dir = os.path.join(self._base_dir, "agents")
        self._transpile_dir = os.path.join(
            self._base_dir, "transpiled", "copilot_studio"
        )
        super().__init__(name=self.name, metadata=self.metadata)

    # ------------------------------------------------------------------
    # perform — action router
    # ------------------------------------------------------------------

    def perform(self, **kwargs):
        action = kwargs.get("action", "")
        try:
            if action == "assimilate":
                return self._action_assimilate(
                    url=kwargs.get("url"),
                    dry_run=kwargs.get("dry_run", False),
                )
            elif action == "generate":
                url = kwargs.get("url")
                analysis = kwargs.get("_analysis")
                if not analysis and url:
                    analysis = self._fetch_and_parse(url)
                    if isinstance(analysis, str):
                        return analysis  # error JSON
                if not analysis:
                    return json.dumps(
                        {"status": "error", "message": "Provide url or _analysis"}
                    )
                return self._action_generate(
                    analysis,
                    agent_name=kwargs.get("agent_name"),
                    dry_run=kwargs.get("dry_run", False),
                )
            elif action == "transpile":
                return self._action_transpile(
                    agent_file=kwargs.get("agent_file"),
                    output_dir=kwargs.get("output_dir"),
                    dry_run=kwargs.get("dry_run", False),
                )
            elif action == "deploy":
                return self._action_deploy(
                    solution_dir=kwargs.get("output_dir"),
                    environment_url=kwargs.get("environment_url"),
                    tenant_id=kwargs.get("tenant_id"),
                    dry_run=kwargs.get("dry_run", False),
                )
            elif action == "pipeline":
                return self._action_pipeline(
                    url=kwargs.get("url"),
                    agent_name=kwargs.get("agent_name"),
                    output_dir=kwargs.get("output_dir"),
                    environment_url=kwargs.get("environment_url"),
                    tenant_id=kwargs.get("tenant_id"),
                    dry_run=kwargs.get("dry_run", False),
                )
            elif action == "history":
                return self._action_history()
            else:
                return json.dumps(
                    {
                        "status": "error",
                        "message": f"Unknown action: {action!r}. Use: assimilate, generate, transpile, deploy, pipeline, history.",
                    }
                )
        except Exception as exc:
            return json.dumps({"status": "error", "message": str(exc)})

    # ------------------------------------------------------------------
    # GitHub URL parsing (exposed for tests)
    # ------------------------------------------------------------------

    def _parse_github_url(self, url):
        return _parse_github_url(url)

    # ------------------------------------------------------------------
    # Fetch workflow JSON from GitHub
    # ------------------------------------------------------------------

    def _fetch_workflow(self, url):
        """Fetch an n8n workflow JSON from a GitHub URL. Returns dict."""
        parsed = _parse_github_url(url)
        if not parsed:
            raise ValueError(f"Not a recognized GitHub URL: {url}")
        owner, repo, branch, path = (
            parsed["owner"],
            parsed["repo"],
            parsed["branch"],
            parsed["path"],
        )
        raw_url = (
            f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/{path}"
        )
        token = os.environ.get("GITHUB_TOKEN")
        data = _fetch_raw_text(raw_url, token=token)
        workflow = json.loads(data)
        return workflow

    def _fetch_and_parse(self, url):
        """Fetch + parse in one step. Returns analysis dict or error JSON string."""
        try:
            workflow = self._fetch_workflow(url)
        except Exception as exc:
            return json.dumps({"status": "error", "message": str(exc)})
        result = self._parse_workflow(workflow)
        if result.get("status") == "error":
            return json.dumps(result)
        result["source_url"] = url
        return result

    # ------------------------------------------------------------------
    # Parse n8n workflow JSON
    # ------------------------------------------------------------------

    def _parse_workflow(self, workflow):
        """Analyze an n8n workflow dict into a structured analysis."""
        nodes = workflow.get("nodes")
        if nodes is None:
            return {
                "status": "error",
                "message": "Invalid n8n workflow: missing 'nodes' key.",
            }

        connections = workflow.get("connections", {})
        name = workflow.get("name", "Untitled Workflow")

        # Classify nodes
        parsed_nodes = []
        node_types = {}
        trigger_type = "manual"
        credentials_needed = set()
        external_services = set()

        for node in nodes:
            full_type = node.get("type", "unknown")
            short = _short_type(full_type)
            params = node.get("parameters", {})

            parsed_nodes.append(
                {
                    "name": node.get("name", ""),
                    "type": full_type,
                    "type_short": short,
                    "parameters": params,
                    "credentials": node.get("credentials", {}),
                }
            )

            node_types[short] = node_types.get(short, 0) + 1

            # Trigger detection
            if short in _TRIGGER_TYPES:
                trigger_type = short

            # Credentials
            for cred_type in node.get("credentials", {}):
                credentials_needed.add(cred_type)

            # External services (from URL parameters)
            for key in ("url", "baseUrl", "endpoint"):
                url_val = params.get(key, "")
                if isinstance(url_val, str) and url_val.startswith("http"):
                    try:
                        host = url_val.split("//")[1].split("/")[0]
                        external_services.add(host)
                    except IndexError:
                        pass

        # Build data flow graph from connections
        data_flow = []
        for src_name, conn_data in connections.items():
            for output_group in conn_data.get("main", []):
                if not output_group:
                    continue
                for edge in output_group:
                    data_flow.append(
                        {
                            "from": src_name,
                            "to": edge.get("node", ""),
                            "output_index": edge.get("index", 0),
                        }
                    )

        return {
            "status": "success",
            "workflow_name": name,
            "trigger_type": trigger_type,
            "node_count": len(nodes),
            "nodes": parsed_nodes,
            "node_types": node_types,
            "data_flow": data_flow,
            "external_services": sorted(external_services),
            "credentials_needed": sorted(credentials_needed),
            "settings": workflow.get("settings", {}),
        }

    # ------------------------------------------------------------------
    # Topological sort for execution order
    # ------------------------------------------------------------------

    def _topo_sort(self, analysis):
        """Return node names in execution order (Kahn's algorithm)."""
        nodes_by_name = {n["name"]: n for n in analysis["nodes"]}
        in_degree = {n["name"]: 0 for n in analysis["nodes"]}
        adj = {n["name"]: [] for n in analysis["nodes"]}

        for edge in analysis["data_flow"]:
            src, dst = edge["from"], edge["to"]
            if src in adj and dst in in_degree:
                adj[src].append(dst)
                in_degree[dst] += 1

        queue = [n for n, d in in_degree.items() if d == 0]
        order = []
        while queue:
            node = queue.pop(0)
            order.append(node)
            for neighbor in adj.get(node, []):
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

        # Append any nodes not reached (disconnected)
        for n in nodes_by_name:
            if n not in order:
                order.append(n)

        return order

    # ------------------------------------------------------------------
    # Map n8n node → Python code snippet
    # ------------------------------------------------------------------

    def _map_node_to_code(self, node):
        """Generate Python code lines for a single n8n node (no padding)."""
        short = node["type_short"]
        params = node["parameters"]
        var = _to_snake(node["name"])
        name_comment = f"# --- {node['name']} ({short}) ---"

        # Skip UI-only nodes
        if short == "stickyNote":
            return [name_comment, "pass  # sticky note (UI annotation, skipped)"]

        if short in _TRIGGER_TYPES:
            return [
                name_comment,
                "# Trigger entry point — input comes from perform() kwargs",
                f"_{var}_input = data",
            ]

        # --- Google Sheets → Microsoft Graph Excel ---
        if short == "googleSheets":
            operation = params.get("operation", "read")
            sheet_name = params.get("sheetName", "Sheet1")
            range_val = params.get("range", "A:Z")
            if operation in ("read", "getAll", ""):
                return [
                    name_comment,
                    "# Google Sheets → Microsoft Graph Excel (read)",
                    f"# Original sheet: {sheet_name}, range: {range_val}",
                    f'_{var}_drive_id = os.environ.get("EXCEL_DRIVE_ID", "")',
                    f'_{var}_workbook_id = os.environ.get("EXCEL_WORKBOOK_ID", "")',
                    f"_{var}_sheet = {sheet_name!r}",
                    f"_{var}_range = {range_val!r}",
                    f'_{var}_url = f"https://graph.microsoft.com/v1.0/drives/{{_{var}_drive_id}}/items/{{_{var}_workbook_id}}/workbook/worksheets/{{_{var}_sheet}}/range(address=\'{{_{var}_range}}\')"',
                    f'_{var}_req = urllib.request.Request(_{var}_url)',
                    f'_{var}_token = os.environ.get("GRAPH_ACCESS_TOKEN", "")',
                    f'_{var}_req.add_header("Authorization", f"Bearer {{_{var}_token}}")',
                    f'_{var}_req.add_header("Content-Type", "application/json")',
                    "try:",
                    f"    with urllib.request.urlopen(_{var}_req, timeout=30) as _resp:",
                    f'        _{var}_data = json.loads(_resp.read().decode("utf-8"))',
                    f'    _{var}_rows = _{var}_data.get("values", [])',
                    "except Exception as _err:",
                    f'    _{var}_rows = []',
                    f'    _{var}_data = {{"error": str(_err)}}',
                ]
            else:
                return [
                    name_comment,
                    f"# Google Sheets → Microsoft Graph Excel ({operation})",
                    f"# Original sheet: {sheet_name}",
                    f'_{var}_drive_id = os.environ.get("EXCEL_DRIVE_ID", "")',
                    f'_{var}_workbook_id = os.environ.get("EXCEL_WORKBOOK_ID", "")',
                    f'_{var}_url = f"https://graph.microsoft.com/v1.0/drives/{{_{var}_drive_id}}/items/{{_{var}_workbook_id}}/workbook/worksheets/{sheet_name}/range(address=\'A:Z\')"',
                    f"_{var}_data = {{}}  # TODO: implement {operation} via Graph API",
                ]

        # --- Email Send → Microsoft Graph Outlook ---
        if short in ("emailSend", "gmail", "microsoftOutlook"):
            to_addr = params.get("toEmail", params.get("to", ""))
            subject = params.get("subject", "")
            body_field = params.get("body", params.get("text", ""))
            return [
                name_comment,
                "# Email Send → Microsoft Graph Outlook",
                f'_{var}_to = {to_addr!r} or data.get("to", "")',
                f'_{var}_subject = {subject!r} or data.get("subject", "Report")',
                f'_{var}_body = {body_field!r} or data.get("body", "")',
                f'_{var}_token = os.environ.get("GRAPH_ACCESS_TOKEN", "")',
                f'_{var}_url = "https://graph.microsoft.com/v1.0/me/sendMail"',
                f"_{var}_payload = json.dumps({{",
                f'    "message": {{',
                f'        "subject": _{var}_subject,',
                f'        "body": {{"contentType": "HTML", "content": _{var}_body}},',
                f'        "toRecipients": [{{"emailAddress": {{"address": _{var}_to}}}}]',
                f"    }}",
                f"}})",
                f'_{var}_req = urllib.request.Request(_{var}_url, data=_{var}_payload.encode("utf-8"), method="POST")',
                f'_{var}_req.add_header("Authorization", f"Bearer {{_{var}_token}}")',
                f'_{var}_req.add_header("Content-Type", "application/json")',
                "try:",
                f"    with urllib.request.urlopen(_{var}_req, timeout=30) as _resp:",
                f'        _{var}_result = {{"status": "sent", "code": _resp.status}}',
                "except Exception as _err:",
                f'    _{var}_result = {{"status": "failed", "error": str(_err)}}',
            ]

        if short == "httpRequest":
            url_val = params.get("url", "https://example.com")
            method = params.get("method", "GET").upper()
            return [
                name_comment,
                f"_{var}_url = {url_val!r}",
                f"_{var}_req = urllib.request.Request(_{var}_url, method={method!r})",
                "try:",
                f"    with urllib.request.urlopen(_{var}_req, timeout=30) as _resp:",
                f'        _{var}_data = json.loads(_resp.read().decode("utf-8"))',
                "except Exception as _err:",
                f'    _{var}_data = {{"error": str(_err)}}',
            ]

        if short == "if":
            return [
                name_comment,
                "# Conditional logic (review conditions manually)",
                f"_{var}_passed = True  # TODO: map n8n condition",
            ]

        if short == "switch":
            return [
                name_comment,
                "# Switch logic (review rules manually)",
                f"_{var}_branch = 0  # TODO: map n8n switch rules",
            ]

        if short == "set":
            lines = [name_comment]
            values = params.get("values", {})
            added = False
            for vtype, entries in values.items():
                if isinstance(entries, list):
                    for entry in entries:
                        vname = _to_snake(entry.get("name", "var"))
                        vval = entry.get("value", "")
                        lines.append(f"_{vname} = {vval!r}  # set node")
                        added = True
            if not added:
                lines.append("pass  # set node (no values extracted)")
            return lines

        if short in ("function", "code"):
            code_str = params.get("functionCode", params.get("jsCode", ""))
            lines = [
                name_comment,
                "# Original n8n code (may need manual translation):",
            ]
            for code_line in code_str.split("\n")[:20]:
                lines.append(f"# {code_line}")
            lines.append(f"_{var}_result = {{}}  # TODO: translate")
            return lines

        if short == "merge":
            return [
                name_comment,
                "# Merge node — combine data from multiple branches",
                f"_{var}_result = {{}}",
            ]

        if short == "respondToWebhook":
            return [
                name_comment,
                "# Respond to webhook — return result",
                f"_{var}_result = data",
            ]

        if short == "noOp":
            return [name_comment, "pass  # no-op node"]

        # Unknown node type — emit as comment
        return [
            name_comment,
            f"# Unknown node type: {node['type']}",
            f"# Parameters: {json.dumps(params)[:200]}",
            f"_{var}_result = None",
        ]

    # ------------------------------------------------------------------
    # ASSIMILATE action
    # ------------------------------------------------------------------

    def _action_assimilate(self, url, dry_run=False):
        if not url:
            return json.dumps(
                {"status": "error", "message": "URL is required for assimilate."}
            )
        parsed = _parse_github_url(url)
        if not parsed:
            return json.dumps(
                {"status": "error", "message": f"Not a recognized GitHub URL: {url}"}
            )
        try:
            workflow = self._fetch_workflow(url)
        except Exception as exc:
            return json.dumps({"status": "error", "message": str(exc)})

        analysis = self._parse_workflow(workflow)
        if analysis.get("status") == "error":
            return json.dumps(analysis)

        analysis["source_url"] = url

        # Save report
        if not dry_run:
            os.makedirs(os.path.join(self._data_dir, "reports"), exist_ok=True)
            ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            slug = _to_snake(analysis["workflow_name"])[:40]
            report_path = os.path.join(
                self._data_dir, "reports", f"{ts}_{slug}.json"
            )
            with open(report_path, "w", encoding="utf-8") as f:
                json.dump(analysis, f, indent=2)
            analysis["saved_report"] = report_path

            self._save_history(
                {
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "workflow_name": analysis["workflow_name"],
                    "url": url,
                    "action": "assimilate",
                    "status": "success",
                    "node_count": analysis["node_count"],
                }
            )

        return json.dumps(analysis, indent=2)

    # ------------------------------------------------------------------
    # GENERATE action
    # ------------------------------------------------------------------

    def _action_generate(self, analysis, agent_name=None, dry_run=False):
        """Generate a brainstem agent.py from an n8n workflow analysis."""
        wf_name = analysis.get("workflow_name", "Untitled")
        if agent_name:
            class_name = _to_pascal(agent_name) + "Agent"
            file_slug = _to_snake(agent_name)
        else:
            class_name = _to_pascal(wf_name) + "Agent"
            file_slug = _to_snake(wf_name)

        file_name = f"{file_slug}_agent.py"

        # Build execution order
        exec_order = self._topo_sort(analysis)
        nodes_by_name = {n["name"]: n for n in analysis["nodes"]}

        # Generate node code lines (unindented)
        all_lines = []
        for node_name in exec_order:
            node = nodes_by_name.get(node_name)
            if node:
                lines = self._map_node_to_code(node)
                all_lines.extend(lines)
                all_lines.append("")  # blank line between nodes

        # Indent all node lines to sit inside the try block (3 levels = 12 spaces)
        body_indent = " " * 12
        node_code = "\n".join(f"{body_indent}{line}" if line.strip() else "" for line in all_lines)
        if not node_code.strip():
            node_code = f"{body_indent}pass"

        # Collect external services for description
        services = ", ".join(analysis.get("external_services", [])) or "none"
        trigger = analysis.get("trigger_type", "manual")

        description = (
            f"Auto-generated from n8n workflow '{wf_name}'. "
            f"Trigger: {trigger}. External services: {services}."
        )

        agent_display_name = _to_pascal(agent_name or wf_name)

        lines = [
            '"""',
            f"{class_name} — Auto-generated from n8n workflow: {wf_name}",
            "",
            f"Trigger: {trigger}",
            f"Nodes: {analysis.get('node_count', 0)}",
            f"External services: {services}",
            '"""',
            "",
            "import json",
            "import os",
            "import urllib.request",
            "",
            "try:",
            "    from agents.basic_agent import BasicAgent",
            "except ModuleNotFoundError:",
            "    from basic_agent import BasicAgent",
            "",
            "",
            f"class {class_name}(BasicAgent):",
            "    def __init__(self):",
            f"        self.name = {agent_display_name!r}",
            "        self.metadata = {",
            '            "name": self.name,',
            f'            "description": {description!r},',
            '            "parameters": {',
            '                "type": "object",',
            '                "properties": {',
            '                    "input_data": {',
            '                        "type": "string",',
            '                        "description": "JSON input data for the workflow"',
            "                    }",
            "                },",
            '                "required": []',
            "            }",
            "        }",
            "        super().__init__(name=self.name, metadata=self.metadata)",
            "",
            "    def perform(self, **kwargs):",
            '        input_data = kwargs.get("input_data", "{}")',
            "        try:",
            "            data = json.loads(input_data) if isinstance(input_data, str) else input_data",
            "        except (json.JSONDecodeError, TypeError):",
            "            data = {}",
            "",
            "        try:",
            node_code,
            "",
            '            return json.dumps({"status": "success", "message": "Workflow executed"})',
            "        except Exception as exc:",
            '            return json.dumps({"status": "error", "message": str(exc)})',
            "",
        ]

        code = "\n".join(lines)

        # Validate syntax
        try:
            compile(code, file_name, "exec")
        except SyntaxError as exc:
            return json.dumps(
                {
                    "status": "error",
                    "message": f"Generated code has syntax error: {exc}",
                    "generated_code": code,
                    "file_name": file_name,
                }
            )

        result = {
            "status": "success",
            "class_name": class_name,
            "file_name": file_name,
            "generated_code": code,
        }

        if not dry_run:
            os.makedirs(self._agents_dir, exist_ok=True)
            file_path = os.path.join(self._agents_dir, file_name)
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(code)
            result["file_path"] = file_path

        return json.dumps(result, indent=2)

    # ------------------------------------------------------------------
    # TRANSPILE action
    # ------------------------------------------------------------------

    def _action_transpile(self, agent_file=None, output_dir=None, dry_run=False):
        """Transpile a brainstem agent.py to Copilot Studio solution."""
        if not agent_file:
            return json.dumps(
                {"status": "error", "message": "agent_file path is required."}
            )
        if not os.path.exists(agent_file):
            return json.dumps(
                {"status": "error", "message": f"File not found: {agent_file}"}
            )

        # Parse the agent file with AST
        with open(agent_file, "r", encoding="utf-8") as f:
            source = f.read()

        try:
            tree = ast.parse(source)
        except SyntaxError as exc:
            return json.dumps(
                {"status": "error", "message": f"Syntax error in agent file: {exc}"}
            )

        # Extract agent info
        agent_info = self._extract_agent_info(tree, source)
        agent_name = agent_info.get("class_name", "UnknownAgent")
        slug = _to_snake(agent_name.replace("Agent", ""))

        # Determine output directory
        out_dir = output_dir or os.path.join(self._transpile_dir, slug)

        # Generate solution files
        solution = self._generate_copilot_solution(agent_info)

        if dry_run:
            return json.dumps(
                {
                    "status": "success",
                    "dry_run": True,
                    "agent_name": agent_name,
                    "output_directory": out_dir,
                    "files_generated": list(solution.keys()),
                },
                indent=2,
            )

        # Write files
        os.makedirs(out_dir, exist_ok=True)
        os.makedirs(os.path.join(out_dir, "topics"), exist_ok=True)
        os.makedirs(os.path.join(out_dir, "flows"), exist_ok=True)

        files_written = []
        for filename, content in solution.items():
            if filename.startswith("topic_"):
                fpath = os.path.join(out_dir, "topics", filename)
            elif filename.startswith("flow_"):
                fpath = os.path.join(out_dir, "flows", filename)
            else:
                fpath = os.path.join(out_dir, filename)

            with open(fpath, "w", encoding="utf-8") as f:
                if isinstance(content, dict):
                    json.dump(content, f, indent=2)
                else:
                    f.write(content)
            files_written.append(filename)

        return json.dumps(
            {
                "status": "success",
                "agent_name": agent_name,
                "output_directory": out_dir,
                "files_generated": files_written,
            },
            indent=2,
        )

    def _extract_agent_info(self, tree, source):
        """Extract agent class info from AST."""
        info = {
            "class_name": "UnknownAgent",
            "name": "Unknown",
            "description": "",
            "actions": [],
            "parameters": {},
            "external_calls": [],
        }

        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and "Agent" in node.name:
                info["class_name"] = node.name
                info["description"] = ast.get_docstring(node) or ""

                # Look for self.name and self.metadata in __init__
                for item in node.body:
                    if isinstance(item, ast.FunctionDef) and item.name == "__init__":
                        self._extract_init_info(item, info, source)

                    # Extract actions from perform
                    if isinstance(item, ast.FunctionDef) and item.name == "perform":
                        self._extract_perform_actions(item, info, source)
                break

        # Detect external calls from source
        if re.search(r"urllib\.request|requests\.", source):
            info["external_calls"].append("http")
        if re.search(r"salesforce|simple_salesforce", source, re.I):
            info["external_calls"].append("salesforce")
        if re.search(r"openai|ChatCompletion", source, re.I):
            info["external_calls"].append("azure_openai")
        if re.search(r"graph\.microsoft\.com.*workbook|EXCEL_DRIVE_ID|EXCEL_WORKBOOK_ID", source):
            info["external_calls"].append("excel_online")
        if re.search(r"graph\.microsoft\.com.*sendMail|graph\.microsoft\.com.*me/messages", source):
            info["external_calls"].append("outlook")

        return info

    def _extract_init_info(self, init_node, info, source):
        """Extract name and metadata from __init__."""
        for node in ast.walk(init_node):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Attribute):
                        if target.attr == "name" and isinstance(
                            node.value, ast.Constant
                        ):
                            info["name"] = node.value.value

        # Try regex on source for metadata description
        desc_match = re.search(
            r'"description"\s*:\s*["\'](.+?)["\']', source, re.DOTALL
        )
        if desc_match:
            info["description"] = desc_match.group(1)[:500]

        # Extract parameter properties via regex
        enum_match = re.search(r'"enum"\s*:\s*\[([^\]]+)\]', source)
        if enum_match:
            actions = re.findall(r'"([^"]+)"', enum_match.group(1))
            info["actions"] = [
                a
                for a in actions
                if a not in ("string", "object", "array", "boolean", "integer")
            ]

    def _extract_perform_actions(self, perform_node, info, source):
        """Extract action names from perform method."""
        if info["actions"]:
            return  # Already extracted from enum
        for node in ast.walk(perform_node):
            if isinstance(node, ast.Compare):
                if isinstance(node.left, ast.Name) and node.left.id == "action":
                    for comp in node.comparators:
                        if isinstance(comp, ast.Constant) and isinstance(
                            comp.value, str
                        ):
                            if comp.value not in info["actions"]:
                                info["actions"].append(comp.value)

    def _generate_copilot_solution(self, agent_info):
        """Generate Copilot Studio solution files from agent info."""
        name = agent_info.get("name", "Agent")
        description = agent_info.get("description", "")
        actions = agent_info.get("actions", [])
        ext_calls = agent_info.get("external_calls", [])
        has_excel = "excel_online" in ext_calls
        has_outlook = "outlook" in ext_calls
        has_flows = bool(actions) or has_excel or has_outlook

        solution = {}

        # Connector mapping
        connectors = {}
        if has_excel:
            connectors["excel_online"] = {
                "connectorId": "shared_excelonlinebusiness",
                "displayName": "Excel Online (Business)",
                "authType": "OAuth2",
            }
        if has_outlook:
            connectors["outlook"] = {
                "connectorId": "shared_office365",
                "displayName": "Office 365 Outlook",
                "authType": "OAuth2",
            }
        if "salesforce" in ext_calls:
            connectors["salesforce"] = {
                "connectorId": "shared_salesforce",
                "displayName": "Salesforce",
                "authType": "OAuth2",
            }

        # 1. Agent manifest
        solution["agent_manifest.json"] = {
            "schemaVersion": "1.0",
            "name": name,
            "displayName": name.replace("_", " ").title(),
            "description": description[:500],
            "instructions": (
                f"You are {name}. {description}" if description else f"You are {name}."
            ),
            "primaryLanguage": "en-US",
            "topics": [f"topic_{a}" for a in actions] if actions else ["topic_main"],
            "capabilities": {
                "generativeAnswers": "azure_openai" in ext_calls,
                "powerAutomateFlows": has_flows,
                "connectors": list(connectors.keys()),
            },
            "metadata": {
                "source": "N8nAssimilator Transpiler",
                "transpiled_at": datetime.now(timezone.utc).isoformat(),
                "original_class": agent_info.get("class_name", ""),
            },
        }

        # 2. Topics — build around actual workflow capabilities
        topic_list = []

        if has_excel:
            topic_list.append(("read_data", "Read Data", [
                "get sales data", "read spreadsheet", "show me the data",
                "pull the report data", "get today's numbers",
            ]))
        if has_outlook:
            topic_list.append(("send_report", "Send Report", [
                "send the report", "email the summary", "send sales report",
                "email the daily report", "send it out",
            ]))
        if has_excel and has_outlook:
            topic_list.append(("generate_report", "Generate Report", [
                "generate daily report", "run daily sales report",
                "create and send report", "daily sales summary",
            ]))

        if actions:
            for action_name in actions:
                topic_list.append((action_name, action_name.replace("_", " ").title(), [
                    action_name.replace("_", " "),
                    f"run {action_name.replace('_', ' ')}",
                    f"execute {action_name.replace('_', ' ')}",
                ]))

        if not topic_list:
            topic_list.append(("main", "Main", ["help", "start", name.lower()]))

        for topic_id, display_name, trigger_phrases in topic_list:
            flow_actions = []
            if topic_id in ("read_data", "generate_report") and has_excel:
                flow_actions.append({
                    "kind": "InvokeFlowAction",
                    "flowId": "flow_read_excel",
                    "outputs": {"result": "excelData"},
                })
            if topic_id in ("send_report", "generate_report") and has_outlook:
                flow_actions.append({
                    "kind": "InvokeFlowAction",
                    "flowId": "flow_send_outlook",
                    "outputs": {"result": "sendResult"},
                })
            if not flow_actions:
                flow_actions.append({
                    "kind": "InvokeFlowAction",
                    "flowId": f"flow_{topic_id}",
                })

            flow_actions.append({
                "kind": "SendMessage",
                "message": "${Topic.flowResult}",
            })

            solution[f"topic_{topic_id}.json"] = {
                "kind": "AdaptiveDialog",
                "id": f"topic_{topic_id}",
                "displayName": display_name,
                "triggers": [{
                    "kind": "OnRecognizedIntent",
                    "intent": topic_id,
                    "triggerQueries": trigger_phrases,
                }],
                "actions": flow_actions,
            }

        # 3. Power Automate Flows — real connector-based flows
        if has_excel:
            solution["flow_read_excel.json"] = {
                "name": "flow_read_excel",
                "displayName": "Read Excel Data Flow",
                "description": "Reads sales data from Excel Online via Microsoft Graph",
                "trigger": {
                    "kind": "PowerVirtualAgents",
                    "inputs": {"type": "object", "properties": {}},
                },
                "actions": [
                    {
                        "kind": "ExcelOnline_GetRows",
                        "connector": "shared_excelonlinebusiness",
                        "inputs": {
                            "source": "OneDrive for Business",
                            "drive": "${env:EXCEL_DRIVE_ID}",
                            "file": "${env:EXCEL_WORKBOOK_ID}",
                            "table": "SalesData",
                        },
                        "outputs": {"rows": "salesRows"},
                    },
                    {
                        "kind": "Compose",
                        "inputs": {
                            "expression": "length(body('ExcelOnline_GetRows')?['value'])",
                        },
                        "outputs": {"rowCount": "dataCount"},
                    },
                    {
                        "kind": "Condition",
                        "expression": "@greater(outputs('dataCount'), 0)",
                        "ifTrue": [
                            {
                                "kind": "Compose",
                                "inputs": "Data found: @{outputs('dataCount')} rows",
                            }
                        ],
                        "ifFalse": [
                            {
                                "kind": "Compose",
                                "inputs": "No sales data found for today.",
                            }
                        ],
                    },
                    {
                        "kind": "Response",
                        "inputs": {"result": "@{outputs('Compose')}"},
                    },
                ],
            }

        if has_outlook:
            solution["flow_send_outlook.json"] = {
                "name": "flow_send_outlook",
                "displayName": "Send Report via Outlook Flow",
                "description": "Sends formatted sales report email via Office 365 Outlook",
                "trigger": {
                    "kind": "PowerVirtualAgents",
                    "inputs": {
                        "type": "object",
                        "properties": {
                            "reportBody": {"type": "string", "description": "HTML report content"},
                            "recipientEmail": {"type": "string", "description": "Email recipient"},
                        },
                    },
                },
                "actions": [
                    {
                        "kind": "Office365Outlook_SendEmail",
                        "connector": "shared_office365",
                        "inputs": {
                            "to": "@triggerBody()?['recipientEmail']",
                            "subject": "Daily Sales Report - @{utcNow('yyyy-MM-dd')}",
                            "body": "@triggerBody()?['reportBody']",
                            "importance": "Normal",
                        },
                        "outputs": {"sendResult": "emailSent"},
                    },
                    {
                        "kind": "Response",
                        "inputs": {"result": "Email sent successfully"},
                    },
                ],
            }

        if has_excel and has_outlook:
            solution["flow_generate_report.json"] = {
                "name": "flow_generate_report",
                "displayName": "Generate and Send Daily Report Flow",
                "description": "End-to-end: reads Excel data, formats report, sends via Outlook",
                "trigger": {
                    "kind": "PowerVirtualAgents",
                    "inputs": {"type": "object", "properties": {}},
                },
                "actions": [
                    {
                        "kind": "ExcelOnline_GetRows",
                        "connector": "shared_excelonlinebusiness",
                        "inputs": {
                            "source": "OneDrive for Business",
                            "drive": "${env:EXCEL_DRIVE_ID}",
                            "file": "${env:EXCEL_WORKBOOK_ID}",
                            "table": "SalesData",
                        },
                        "outputs": {"rows": "salesRows"},
                    },
                    {
                        "kind": "Condition",
                        "expression": "@greater(length(body('ExcelOnline_GetRows')?['value']), 0)",
                        "ifTrue": [
                            {
                                "kind": "Compose",
                                "description": "Format HTML report from sales data",
                                "inputs": "@concat('<h2>Daily Sales Report</h2><p>Total rows: ', string(length(body('ExcelOnline_GetRows')?['value'])), '</p>')",
                            },
                            {
                                "kind": "Office365Outlook_SendEmail",
                                "connector": "shared_office365",
                                "inputs": {
                                    "to": "${env:REPORT_RECIPIENT}",
                                    "subject": "Daily Sales Report - @{utcNow('yyyy-MM-dd')}",
                                    "body": "@outputs('Compose')",
                                    "importance": "Normal",
                                },
                            },
                            {
                                "kind": "Response",
                                "inputs": {"result": "Report generated and sent successfully"},
                            },
                        ],
                        "ifFalse": [
                            {
                                "kind": "Office365Outlook_SendEmail",
                                "connector": "shared_office365",
                                "inputs": {
                                    "to": "${env:REPORT_RECIPIENT}",
                                    "subject": "Daily Sales Report - No Data - @{utcNow('yyyy-MM-dd')}",
                                    "body": "<p>No sales data available for today.</p>",
                                    "importance": "Low",
                                },
                            },
                            {
                                "kind": "Response",
                                "inputs": {"result": "No data found. Notification email sent."},
                            },
                        ],
                    },
                ],
            }

        # Generic flows for explicit actions (if any)
        for action_name in actions:
            fkey = f"flow_{action_name}.json"
            if fkey not in solution:
                solution[fkey] = {
                    "name": f"flow_{action_name}",
                    "displayName": f"{action_name.replace('_', ' ').title()} Flow",
                    "trigger": {
                        "kind": "PowerVirtualAgents",
                        "inputs": {"action": action_name},
                    },
                    "actions": [
                        {"kind": "Response", "inputs": {"result": f"Executed {action_name}"}},
                    ],
                }

        # 4. Connectors config
        if connectors:
            solution["connectors.json"] = {
                "connectors": connectors,
                "instructions": "Configure each connector in Power Platform admin center before importing.",
            }

        # 5. Deployment guide
        solution["DEPLOYMENT_GUIDE.md"] = self._generate_deployment_guide(
            name, agent_info
        )

        return solution

    def _generate_deployment_guide(self, name, agent_info):
        """Generate deployment guide markdown."""
        actions = agent_info.get("actions", [])
        guide = f"""# Deployment Guide: {name}

## Prerequisites
1. Copilot Studio license (included in M365 E3/E5 or standalone)
2. Power Platform environment
3. Power Platform CLI (`pac`) installed: `npm install -g pac-cli` or `dotnet tool install --global Microsoft.PowerApps.CLI.Tool`

## Option 1: Deploy via pac CLI

```bash
# Authenticate
pac auth create --environment https://your-org.crm.dynamics.com

# Import the solution
pac solution import --path ./solution.zip

# Verify
pac solution list
```

## Option 2: Manual Import

1. Go to [Power Platform Admin Center](https://admin.powerplatform.microsoft.com)
2. Select your environment
3. Go to Solutions > Import
4. Upload the solution package

## Post-Deployment

1. Open Copilot Studio
2. Find agent: **{name}**
3. Review and customize instructions
4. Test in the test canvas
5. Publish and configure channels (Teams, Web, etc.)

## Topics
"""
        for a in actions:
            guide += f"- **{a.replace('_', ' ').title()}**\n"

        if agent_info.get("external_calls"):
            guide += "\n## Required Connectors\n"
            for call in agent_info["external_calls"]:
                guide += f"- {call}\n"

        guide += f"\n---\n*Generated by N8nAssimilator on {datetime.now(timezone.utc).strftime('%Y-%m-%d')}*\n"
        return guide

    # ------------------------------------------------------------------
    # DEPLOY action
    # ------------------------------------------------------------------

    def _action_deploy(self, solution_dir=None, environment_url=None, tenant_id=None, dry_run=False):
        """Deploy transpiled solution via pac CLI."""
        pac_path = shutil.which("pac")

        if not solution_dir:
            return json.dumps(
                {"status": "error", "message": "output_dir (solution directory) is required."}
            )
        if not os.path.exists(solution_dir):
            return json.dumps(
                {"status": "error", "message": f"Solution directory not found: {solution_dir}"}
            )

        commands = []
        if environment_url:
            commands.append(f"pac auth create --environment {environment_url}")
        commands.append(f"pac solution import --path {solution_dir}")

        if dry_run:
            return json.dumps(
                {
                    "status": "dry_run",
                    "pac_available": pac_path is not None,
                    "commands": commands,
                    "message": "Dry run — these commands would be executed.",
                },
                indent=2,
            )

        if not pac_path:
            return json.dumps(
                {
                    "status": "manual",
                    "message": "pac CLI not found. Install with: npm install -g pac-cli",
                    "manual_commands": commands,
                    "alternative": "Import the solution manually via Power Platform Admin Center.",
                },
                indent=2,
            )

        # Execute pac commands
        results = []
        for cmd in commands:
            try:
                proc = subprocess.run(
                    cmd.split(),
                    capture_output=True,
                    text=True,
                    timeout=120,
                )
                results.append(
                    {
                        "command": cmd,
                        "returncode": proc.returncode,
                        "stdout": proc.stdout[:1000],
                        "stderr": proc.stderr[:1000],
                    }
                )
                if proc.returncode != 0:
                    return json.dumps(
                        {
                            "status": "error",
                            "message": f"pac command failed: {cmd}",
                            "details": results,
                        },
                        indent=2,
                    )
            except Exception as exc:
                return json.dumps(
                    {"status": "error", "message": f"Error running pac: {exc}"}
                )

        return json.dumps(
            {"status": "success", "message": "Solution deployed.", "results": results},
            indent=2,
        )

    # ------------------------------------------------------------------
    # PIPELINE action
    # ------------------------------------------------------------------

    def _action_pipeline(self, url=None, agent_name=None, output_dir=None,
                         environment_url=None, tenant_id=None, dry_run=False):
        """Run the full pipeline: assimilate → generate → transpile → deploy."""
        stages = {}

        # Stage 1: Assimilate
        try:
            if not url:
                return json.dumps(
                    {"status": "error", "message": "URL is required for pipeline."}
                )

            workflow = self._fetch_workflow(url)
            analysis = self._parse_workflow(workflow)
            if analysis.get("status") == "error":
                return json.dumps(
                    {"status": "error", "stage": "assimilate", "details": analysis}
                )
            analysis["source_url"] = url

            if not dry_run:
                os.makedirs(os.path.join(self._data_dir, "reports"), exist_ok=True)
                ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
                slug = _to_snake(analysis["workflow_name"])[:40]
                report_path = os.path.join(
                    self._data_dir, "reports", f"{ts}_{slug}.json"
                )
                with open(report_path, "w", encoding="utf-8") as f:
                    json.dump(analysis, f, indent=2)

            stages["assimilate"] = {
                "status": "success",
                "workflow_name": analysis["workflow_name"],
                "node_count": analysis["node_count"],
            }
        except Exception as exc:
            return json.dumps(
                {"status": "error", "stage": "assimilate", "message": str(exc), "stages": stages}
            )

        # Stage 2: Generate
        try:
            gen_result = json.loads(
                self._action_generate(analysis, agent_name=agent_name, dry_run=dry_run)
            )
            if gen_result.get("status") != "success":
                return json.dumps(
                    {"status": "error", "stage": "generate", "details": gen_result, "stages": stages}
                )
            stages["generate"] = {
                "status": "success",
                "file_name": gen_result.get("file_name"),
                "class_name": gen_result.get("class_name"),
            }
            agent_file_path = gen_result.get("file_path")
        except Exception as exc:
            return json.dumps(
                {"status": "error", "stage": "generate", "message": str(exc), "stages": stages}
            )

        # Stage 3: Transpile
        try:
            if dry_run:
                # In dry run, we still have the generated code but no file
                # Write to a temp file for transpilation
                import tempfile

                tmp_file = os.path.join(
                    tempfile.gettempdir(), gen_result.get("file_name", "tmp_agent.py")
                )
                with open(tmp_file, "w") as f:
                    f.write(gen_result.get("generated_code", ""))
                agent_file_path = tmp_file

            if agent_file_path:
                trans_result = json.loads(
                    self._action_transpile(
                        agent_file=agent_file_path,
                        output_dir=output_dir,
                        dry_run=dry_run,
                    )
                )
                stages["transpile"] = {
                    "status": trans_result.get("status", "unknown"),
                    "files_generated": trans_result.get("files_generated", []),
                }
        except Exception as exc:
            stages["transpile"] = {"status": "error", "message": str(exc)}

        # Stage 4: Deploy (only if not dry_run and transpile succeeded)
        if not dry_run and stages.get("transpile", {}).get("status") == "success":
            try:
                deploy_result = json.loads(
                    self._action_deploy(
                        solution_dir=output_dir
                        or os.path.join(
                            self._transpile_dir,
                            _to_snake(
                                (agent_name or analysis["workflow_name"]).replace(
                                    "Agent", ""
                                )
                            ),
                        ),
                        environment_url=environment_url,
                        tenant_id=tenant_id,
                    )
                )
                stages["deploy"] = deploy_result
            except Exception as exc:
                stages["deploy"] = {"status": "error", "message": str(exc)}

        # Save to history
        if not dry_run:
            self._save_history(
                {
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "workflow_name": analysis["workflow_name"],
                    "url": url,
                    "action": "pipeline",
                    "status": "success",
                    "stages": list(stages.keys()),
                }
            )

        return json.dumps(
            {"status": "success", "stages": stages}, indent=2
        )

    # ------------------------------------------------------------------
    # HISTORY action
    # ------------------------------------------------------------------

    def _action_history(self):
        """Return past assimilation history."""
        entries = self._load_history()
        return json.dumps(
            {"status": "success", "entries": entries, "total": len(entries)},
            indent=2,
        )

    # ------------------------------------------------------------------
    # History persistence
    # ------------------------------------------------------------------

    def _load_history(self):
        """Load history from JSON file."""
        path = os.path.join(self._data_dir, "history.json")
        if not os.path.exists(path):
            return []
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return []

    def _save_history(self, entry):
        """Append an entry to history."""
        os.makedirs(self._data_dir, exist_ok=True)
        history = self._load_history()
        history.append(entry)
        path = os.path.join(self._data_dir, "history.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(history, f, indent=2)
