"""
CopilotStudioDeploy — Pushes exported Copilot Studio YAML to the cloud.

Wraps the manage-agent CLI (LanguageServerHost LSP binary) to push, pull,
and manage the RAPP Brainstem agent in Copilot Studio. Handles authentication
via interactive browser login (tokens cached in OS credential store).

Actions:
  list-envs   — list available Power Platform environments
  list-agents — list agents in the target environment
  push        — push local YAML to Copilot Studio cloud
  pull        — pull cloud changes to local YAML
  changes     — show diff between local and cloud
  auth        — pre-authenticate (opens browser)

Follows the Single File Agent pattern (Constitution Article IV).
"""

import json
import subprocess
import sys
from pathlib import Path

from agents.basic_agent import BasicAgent


# Path to the manage-agent CLI bundle (installed by Copilot Studio plugin)
_MANAGE_AGENT_SCRIPT = Path.home() / ".claude" / "plugins" / "cache" / \
    "skills-for-copilot-studio" / "copilot-studio" / "1.0.4" / \
    "scripts" / "manage-agent.bundle.js"


def _find_conn_json(workspace: Path) -> dict | None:
    """Load .mcs/conn.json from workspace or template fallback."""
    conn_path = workspace / ".mcs" / "conn.json"
    if conn_path.exists():
        return json.loads(conn_path.read_text(encoding="utf-8"))

    # Fallback: use the template's connection info (same environment)
    template_conn = workspace.parent.parent / ".brainstem_data" / "shared" / \
        "Template Agent" / ".mcs" / "conn.json"
    if template_conn.exists():
        return json.loads(template_conn.read_text(encoding="utf-8"))

    return None


def _build_env_args(conn: dict) -> list[str]:
    """Build CLI flags from conn.json data."""
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
    """Run the manage-agent CLI and return parsed JSON output."""
    if not _MANAGE_AGENT_SCRIPT.exists():
        return {
            "status": "error",
            "error": (
                "manage-agent.bundle.js not found. "
                "Install the Copilot Studio plugin: "
                "skills-for-copilot-studio in ~/.claude/plugins/"
            )
        }

    node = "node"
    full_cmd = [node, str(_MANAGE_AGENT_SCRIPT), cmd] + (extra_args or [])

    try:
        result = subprocess.run(
            full_cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )

        output = result.stdout.strip()
        stderr = result.stderr.strip()

        # The CLI emits JSON on stdout
        if output:
            try:
                return json.loads(output)
            except json.JSONDecodeError:
                return {
                    "status": "success" if result.returncode == 0 else "error",
                    "output": output,
                    "stderr": stderr,
                }

        if result.returncode != 0:
            return {"status": "error", "error": stderr or f"Exit code {result.returncode}"}

        return {"status": "success", "output": stderr or "(no output)"}

    except subprocess.TimeoutExpired:
        return {"status": "error", "error": f"Command timed out after {timeout}s"}
    except FileNotFoundError:
        return {"status": "error", "error": "Node.js not found on PATH"}
    except Exception as e:
        return {"status": "error", "error": str(e)}


class CopilotStudioDeployAgent(BasicAgent):
    def __init__(self):
        self.name = "CopilotStudioDeploy"
        self.metadata = {
            "name": self.name,
            "description": (
                "Deploys Copilot Studio agent YAML to the cloud. "
                "Push local changes, pull remote updates, list environments "
                "and agents, or check diffs. Opens browser for authentication."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "description": "Operation to perform.",
                        "enum": [
                            "push", "pull", "changes",
                            "list-envs", "list-agents", "auth"
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
                        "description": "Azure AD tenant ID (auto-detected from conn.json if available)"
                    },
                    "environment_id": {
                        "type": "string",
                        "description": "Power Platform environment ID (auto-detected from conn.json if available)"
                    }
                },
                "required": []
            }
        }
        super().__init__(name=self.name, metadata=self.metadata)

    def perform(self, **kwargs):
        action = kwargs.get("action", "push")
        project_root = Path(__file__).resolve().parent.parent
        workspace = Path(kwargs.get(
            "workspace",
            project_root / "copilot-studio" / "RAPP Brainstem"
        ))

        # Validate workspace exists for push/pull/changes
        if action in ("push", "pull", "changes"):
            agent_yml = workspace / "agent.mcs.yml"
            if not agent_yml.exists():
                return json.dumps({
                    "status": "error",
                    "error": (
                        f"No agent.mcs.yml found in {workspace}. "
                        "Run CopilotStudioExport with action='export' first."
                    )
                }, indent=2)

        # Load connection info
        conn = _find_conn_json(workspace)

        # Allow CLI overrides
        if kwargs.get("tenant_id"):
            if not conn:
                conn = {"AccountInfo": {}}
            conn.setdefault("AccountInfo", {})["TenantId"] = kwargs["tenant_id"]
        if kwargs.get("environment_id"):
            if not conn:
                conn = {"AccountInfo": {}}
            conn["EnvironmentId"] = kwargs["environment_id"]

        # Dispatch
        if action == "auth":
            return self._do_auth(conn)
        elif action == "list-envs":
            return self._do_list_envs(conn)
        elif action == "list-agents":
            return self._do_list_agents(conn)
        elif action == "push":
            return self._do_push(workspace, conn)
        elif action == "pull":
            return self._do_pull(workspace, conn)
        elif action == "changes":
            return self._do_changes(workspace, conn)
        else:
            return json.dumps({"status": "error", "error": f"Unknown action: {action}"})

    def _do_auth(self, conn: dict | None) -> str:
        args = []
        if conn:
            args = _build_env_args(conn)
        result = _run_manage_agent("auth", args, timeout=120)
        return json.dumps(result, indent=2)

    def _do_list_envs(self, conn: dict | None) -> str:
        if not conn or not conn.get("AccountInfo", {}).get("TenantId"):
            return json.dumps({
                "status": "error",
                "error": "tenant_id required. Pass it as a parameter or ensure conn.json exists."
            }, indent=2)
        args = _build_env_args(conn)
        result = _run_manage_agent("list-envs", args)
        return json.dumps(result, indent=2)

    def _do_list_agents(self, conn: dict | None) -> str:
        if not conn or not conn.get("EnvironmentId"):
            return json.dumps({
                "status": "error",
                "error": "environment_id required. Pass it as a parameter or ensure conn.json exists."
            }, indent=2)
        args = _build_env_args(conn)
        result = _run_manage_agent("list-agents", args)
        return json.dumps(result, indent=2)

    def _do_push(self, workspace: Path, conn: dict | None) -> str:
        args = ["--workspace", str(workspace)]
        if conn:
            args += _build_env_args(conn)
        result = _run_manage_agent("push", args, timeout=300)
        return json.dumps(result, indent=2)

    def _do_pull(self, workspace: Path, conn: dict | None) -> str:
        args = ["--workspace", str(workspace)]
        if conn:
            args += _build_env_args(conn)
        result = _run_manage_agent("pull", args, timeout=300)
        return json.dumps(result, indent=2)

    def _do_changes(self, workspace: Path, conn: dict | None) -> str:
        args = ["--workspace", str(workspace)]
        if conn:
            args += _build_env_args(conn)
        result = _run_manage_agent("changes", args)
        return json.dumps(result, indent=2)
