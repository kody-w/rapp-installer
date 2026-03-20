"""
CopilotStudioTest — Runs Playwright tests against the Copilot Studio Test Chat.

Automates browser-based testing of the deployed RAPP Brainstem agent directly
in the Copilot Studio UI. Tests topic routing, greeting, memory, HackerNews,
and online research flows.

Actions:
  run     — run all Playwright tests (headed, for first auth / watching)
  quick   — run a single utterance test
  results — show latest test results

Follows the Single File Agent pattern (Constitution Article IV).
"""

import json
import subprocess
from pathlib import Path

from agents.basic_agent import BasicAgent


class CopilotStudioTestAgent(BasicAgent):
    def __init__(self):
        self.name = "CopilotStudioTest"
        self.metadata = {
            "name": self.name,
            "description": (
                "Runs automated Playwright tests against the RAPP Brainstem "
                "agent in Copilot Studio's Test Chat panel. Tests topic routing, "
                "greeting, memory, and research flows in a real browser."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "description": "What to do.",
                        "enum": ["run", "quick", "results"]
                    },
                    "utterance": {
                        "type": "string",
                        "description": "For action=quick: the message to send to the agent."
                    },
                    "headed": {
                        "type": "boolean",
                        "description": "Run with visible browser window (default: true for first run, false after auth saved)."
                    }
                },
                "required": []
            }
        }
        super().__init__(name=self.name, metadata=self.metadata)

    def perform(self, **kwargs):
        action = kwargs.get("action", "run")
        project_root = Path(__file__).resolve().parent.parent

        if action == "run":
            return self._run_tests(project_root, kwargs.get("headed"))
        elif action == "quick":
            utterance = kwargs.get("utterance", "Hi there!")
            return self._quick_test(project_root, utterance, kwargs.get("headed"))
        elif action == "results":
            return self._show_results(project_root)
        else:
            return json.dumps({"status": "error", "message": f"Unknown action: {action}"})

    def _run_tests(self, project_root: Path, headed: bool | None) -> str:
        """Run the full Playwright test suite."""
        auth_exists = (project_root / "tests" / ".auth" / "state.json").exists()

        cmd = ["npx", "playwright", "test", "tests/copilot_studio_test.js"]

        # Default to headed if no auth state saved yet
        if headed is None:
            headed = not auth_exists
        if headed:
            cmd.append("--headed")

        try:
            result = subprocess.run(
                cmd,
                cwd=str(project_root),
                capture_output=True,
                text=True,
                timeout=600,  # 10 min max for full suite
            )

            output = {
                "status": "success" if result.returncode == 0 else "failed",
                "exit_code": result.returncode,
                "stdout": result.stdout[-3000:] if result.stdout else "",
                "stderr": result.stderr[-2000:] if result.stderr else "",
            }

            # Check for screenshots
            results_dir = project_root / "tests" / "test-results"
            if results_dir.exists():
                screenshots = list(results_dir.glob("*.png"))
                output["screenshots"] = [str(s) for s in screenshots]

            return json.dumps(output, indent=2)

        except subprocess.TimeoutExpired:
            return json.dumps({"status": "error", "message": "Tests timed out after 10 minutes"})
        except FileNotFoundError:
            return json.dumps({"status": "error", "message": "npx not found — install Node.js"})
        except Exception as e:
            return json.dumps({"status": "error", "message": str(e)})

    def _quick_test(self, project_root: Path, utterance: str, headed: bool | None) -> str:
        """Run a single utterance test using the external quick_test.js script."""
        test_script = project_root / "tests" / "quick_test.js"
        if not test_script.exists():
            return json.dumps({"status": "error", "message": "tests/quick_test.js not found"})

        auth_exists = (project_root / "tests" / ".auth" / "state.json").exists()
        cmd = ["node", str(test_script), utterance]
        if headed or (headed is None and not auth_exists):
            cmd.append("--headed")

        try:
            result = subprocess.run(
                cmd,
                cwd=str(project_root),
                capture_output=True,
                text=True,
                timeout=300,
            )

            # Parse the last JSON line from stdout
            lines = [l.strip() for l in result.stdout.strip().split("\n") if l.strip()]
            output = {"status": "unknown", "raw": result.stdout[-2000:]}

            for line in reversed(lines):
                try:
                    parsed = json.loads(line)
                    if "status" in parsed or "response" in parsed:
                        output = parsed
                        break
                except json.JSONDecodeError:
                    continue

            if result.stderr:
                output["log"] = result.stderr[-1000:]

            return json.dumps(output, indent=2)

        except subprocess.TimeoutExpired:
            return json.dumps({"status": "error", "message": "Test timed out after 5 minutes"})
        except Exception as e:
            return json.dumps({"status": "error", "message": str(e)})

    def _show_results(self, project_root: Path) -> str:
        """Show latest test results and screenshots."""
        results_dir = project_root / "tests" / "test-results"
        if not results_dir.exists():
            return json.dumps({"status": "info", "message": "No test results yet. Run tests first."})

        screenshots = sorted(results_dir.glob("*.png"))
        html_report = project_root / "playwright-report" / "index.html"

        return json.dumps({
            "status": "success",
            "screenshots": [str(s) for s in screenshots],
            "html_report": str(html_report) if html_report.exists() else None,
            "results_dir": str(results_dir),
        }, indent=2)
