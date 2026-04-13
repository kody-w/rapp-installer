#!/usr/bin/env python3
"""Tests for the n8n Workflow Assimilator Agent (TDD — written before agent)."""

import os
import sys
import ast
import json
import shutil
import tempfile
import unittest
from unittest.mock import patch, MagicMock
from io import BytesIO

# Ensure brainstem dir is importable
BRAINSTEM_DIR = os.path.dirname(os.path.abspath(__file__))
if BRAINSTEM_DIR not in sys.path:
    sys.path.insert(0, BRAINSTEM_DIR)

# ---------------------------------------------------------------------------
# Mock n8n workflow fixtures
# ---------------------------------------------------------------------------

MOCK_SIMPLE_WORKFLOW = {
    "name": "Simple HTTP Workflow",
    "nodes": [
        {
            "type": "n8n-nodes-base.webhook",
            "name": "Webhook",
            "parameters": {"path": "test", "httpMethod": "POST"},
            "position": [250, 300],
        },
        {
            "type": "n8n-nodes-base.httpRequest",
            "name": "HTTP Request",
            "parameters": {
                "url": "https://api.example.com/data",
                "method": "GET",
                "options": {},
            },
            "position": [450, 300],
        },
    ],
    "connections": {
        "Webhook": {
            "main": [[{"node": "HTTP Request", "type": "main", "index": 0}]]
        }
    },
    "settings": {},
}

MOCK_COMPLEX_WORKFLOW = {
    "name": "Complex Data Pipeline",
    "nodes": [
        {
            "type": "n8n-nodes-base.webhook",
            "name": "Trigger",
            "parameters": {"path": "pipeline", "httpMethod": "POST"},
            "position": [100, 300],
        },
        {
            "type": "n8n-nodes-base.httpRequest",
            "name": "Fetch Data",
            "parameters": {
                "url": "https://api.example.com/items",
                "method": "GET",
            },
            "credentials": {"httpBasicAuth": {"id": "1"}},
            "position": [300, 300],
        },
        {
            "type": "n8n-nodes-base.if",
            "name": "Check Status",
            "parameters": {
                "conditions": {
                    "number": [
                        {
                            "value1": "={{$json.status}}",
                            "operation": "equal",
                            "value2": 200,
                        }
                    ]
                }
            },
            "position": [500, 300],
        },
        {
            "type": "n8n-nodes-base.set",
            "name": "Format Output",
            "parameters": {
                "values": {
                    "string": [{"name": "result", "value": "={{$json.data}}"}]
                }
            },
            "position": [700, 200],
        },
        {
            "type": "n8n-nodes-base.respondToWebhook",
            "name": "Respond",
            "parameters": {"respondWith": "json"},
            "position": [900, 300],
        },
    ],
    "connections": {
        "Trigger": {
            "main": [[{"node": "Fetch Data", "type": "main", "index": 0}]]
        },
        "Fetch Data": {
            "main": [[{"node": "Check Status", "type": "main", "index": 0}]]
        },
        "Check Status": {
            "main": [
                [{"node": "Format Output", "type": "main", "index": 0}],
                [{"node": "Respond", "type": "main", "index": 0}],
            ]
        },
        "Format Output": {
            "main": [[{"node": "Respond", "type": "main", "index": 0}]]
        },
    },
    "settings": {},
}

MOCK_MALFORMED_WORKFLOW = {"name": "Bad Workflow", "settings": {}}


def _make_agent():
    """Import and instantiate the agent."""
    from agents.n8n_assimilator_agent import N8nAssimilatorAgent

    return N8nAssimilatorAgent()


# ===================================================================
# Test 1: GitHub URL Parsing
# ===================================================================


class TestGitHubUrlParsing(unittest.TestCase):
    """Test _parse_github_url extracts owner/repo/branch/path."""

    def setUp(self):
        self.agent = _make_agent()

    def test_parse_standard_blob_url(self):
        result = self.agent._parse_github_url(
            "https://github.com/owner/repo/blob/main/workflow.json"
        )
        self.assertEqual(result["owner"], "owner")
        self.assertEqual(result["repo"], "repo")
        self.assertEqual(result["branch"], "main")
        self.assertEqual(result["path"], "workflow.json")

    def test_parse_nested_path_url(self):
        result = self.agent._parse_github_url(
            "https://github.com/owner/repo/blob/main/workflows/sub/file.json"
        )
        self.assertEqual(result["path"], "workflows/sub/file.json")

    def test_parse_raw_url(self):
        result = self.agent._parse_github_url(
            "https://raw.githubusercontent.com/owner/repo/main/workflow.json"
        )
        self.assertEqual(result["owner"], "owner")
        self.assertEqual(result["repo"], "repo")
        self.assertEqual(result["path"], "workflow.json")

    def test_parse_different_branch(self):
        result = self.agent._parse_github_url(
            "https://github.com/owner/repo/blob/develop/flow.json"
        )
        self.assertEqual(result["branch"], "develop")

    def test_invalid_url_returns_none(self):
        result = self.agent._parse_github_url("https://example.com/not-github")
        self.assertIsNone(result)

    def test_non_json_url_still_parses(self):
        result = self.agent._parse_github_url(
            "https://github.com/owner/repo/blob/main/readme.md"
        )
        self.assertIsNotNone(result)
        self.assertEqual(result["path"], "readme.md")


# ===================================================================
# Test 2: n8n Workflow Parsing
# ===================================================================


class TestWorkflowParsing(unittest.TestCase):
    """Test _parse_workflow produces correct analysis from n8n JSON."""

    def setUp(self):
        self.agent = _make_agent()

    def test_parse_simple_workflow(self):
        result = self.agent._parse_workflow(MOCK_SIMPLE_WORKFLOW)
        self.assertEqual(result["workflow_name"], "Simple HTTP Workflow")
        self.assertEqual(result["node_count"], 2)

    def test_parse_complex_workflow(self):
        result = self.agent._parse_workflow(MOCK_COMPLEX_WORKFLOW)
        self.assertEqual(result["node_count"], 5)

    def test_workflow_name_extraction(self):
        result = self.agent._parse_workflow(MOCK_SIMPLE_WORKFLOW)
        self.assertEqual(result["workflow_name"], "Simple HTTP Workflow")

    def test_trigger_type_detection(self):
        result = self.agent._parse_workflow(MOCK_SIMPLE_WORKFLOW)
        self.assertEqual(result["trigger_type"], "webhook")

    def test_node_type_counting(self):
        result = self.agent._parse_workflow(MOCK_COMPLEX_WORKFLOW)
        self.assertIn("httpRequest", result["node_types"])
        self.assertIn("if", result["node_types"])
        self.assertIn("set", result["node_types"])

    def test_data_flow_graph(self):
        result = self.agent._parse_workflow(MOCK_SIMPLE_WORKFLOW)
        self.assertTrue(len(result["data_flow"]) > 0)
        edge = result["data_flow"][0]
        self.assertEqual(edge["from"], "Webhook")
        self.assertEqual(edge["to"], "HTTP Request")

    def test_credential_detection(self):
        result = self.agent._parse_workflow(MOCK_COMPLEX_WORKFLOW)
        self.assertIn("httpBasicAuth", result["credentials_needed"])

    def test_external_service_detection(self):
        result = self.agent._parse_workflow(MOCK_COMPLEX_WORKFLOW)
        self.assertTrue(
            any("example.com" in s for s in result["external_services"])
        )

    def test_malformed_workflow_returns_error(self):
        result = self.agent._parse_workflow(MOCK_MALFORMED_WORKFLOW)
        self.assertEqual(result["status"], "error")


# ===================================================================
# Test 3: Agent .py Generation
# ===================================================================


class TestAgentGeneration(unittest.TestCase):
    """Test _action_generate produces valid brainstem agent code."""

    def setUp(self):
        self.agent = _make_agent()
        self._tmp = tempfile.mkdtemp()
        self.agent._agents_dir = self._tmp
        self.analysis = self.agent._parse_workflow(MOCK_SIMPLE_WORKFLOW)

    def tearDown(self):
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_generated_code_is_valid_python(self):
        result = json.loads(
            self.agent._action_generate(self.analysis, agent_name="TestFlow")
        )
        code = result["generated_code"]
        # Must not raise SyntaxError
        compile(code, "<test>", "exec")

    def test_generated_class_extends_basic_agent(self):
        result = json.loads(
            self.agent._action_generate(self.analysis, agent_name="TestFlow")
        )
        code = result["generated_code"]
        tree = ast.parse(code)
        classes = [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]
        self.assertTrue(len(classes) >= 1)
        # Check inheritance
        agent_class = classes[0]
        base_names = []
        for base in agent_class.bases:
            if isinstance(base, ast.Name):
                base_names.append(base.id)
            elif isinstance(base, ast.Attribute):
                base_names.append(base.attr)
        self.assertIn("BasicAgent", base_names)

    def test_generated_class_has_perform(self):
        result = json.loads(
            self.agent._action_generate(self.analysis, agent_name="TestFlow")
        )
        code = result["generated_code"]
        tree = ast.parse(code)
        classes = [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]
        methods = [
            n.name
            for n in ast.walk(classes[0])
            if isinstance(n, ast.FunctionDef)
        ]
        self.assertIn("perform", methods)

    def test_generated_metadata_has_required_fields(self):
        result = json.loads(
            self.agent._action_generate(self.analysis, agent_name="TestFlow")
        )
        code = result["generated_code"]
        # Execute the code to check metadata
        ns = {}
        exec(code, ns)
        # Find the agent class
        agent_cls = None
        for v in ns.values():
            if isinstance(v, type) and v.__name__.endswith("Agent"):
                agent_cls = v
                break
        self.assertIsNotNone(agent_cls)
        instance = agent_cls()
        self.assertIn("name", instance.metadata)
        self.assertIn("description", instance.metadata)
        self.assertIn("parameters", instance.metadata)

    def test_agent_name_derivation(self):
        result = json.loads(
            self.agent._action_generate(
                self.analysis, agent_name="My Cool Flow"
            )
        )
        self.assertIn("MyCoolFlowAgent", result["generated_code"])
        self.assertTrue(result["file_name"].endswith("_agent.py"))

    def test_http_request_node_generates_urllib(self):
        result = json.loads(
            self.agent._action_generate(self.analysis, agent_name="TestFlow")
        )
        code = result["generated_code"]
        self.assertIn("urllib.request", code)

    def test_dry_run_does_not_write_file(self):
        self.agent._action_generate(
            self.analysis, agent_name="TestFlow", dry_run=True
        )
        files = os.listdir(self._tmp)
        py_files = [f for f in files if f.endswith("_agent.py")]
        self.assertEqual(len(py_files), 0)


# ===================================================================
# Test 4: Copilot Studio Transpilation
# ===================================================================


class TestTranspilation(unittest.TestCase):
    """Test _action_transpile produces valid Copilot Studio solution files."""

    def setUp(self):
        self.agent = _make_agent()
        self._tmp = tempfile.mkdtemp()
        self.agent._transpile_dir = self._tmp

        # Write a minimal agent.py to transpile
        self._agent_file = os.path.join(self._tmp, "test_agent.py")
        with open(self._agent_file, "w") as f:
            f.write(
                '''
from agents.basic_agent import BasicAgent

class TestAgent(BasicAgent):
    def __init__(self):
        self.name = "Test"
        self.metadata = {
            "name": "Test",
            "description": "A test agent.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["run", "status"],
                        "description": "Action to perform"
                    },
                    "query": {"type": "string", "description": "Input query"}
                },
                "required": ["action"]
            }
        }
        super().__init__(name=self.name, metadata=self.metadata)

    def perform(self, **kwargs):
        action = kwargs.get("action", "run")
        if action == "run":
            return "Running"
        elif action == "status":
            return "OK"
        return "Unknown action"
'''
            )

    def tearDown(self):
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_manifest_json_structure(self):
        result = json.loads(
            self.agent._action_transpile(agent_file=self._agent_file)
        )
        self.assertEqual(result["status"], "success")
        # Read generated manifest
        out_dir = result["output_directory"]
        manifest_path = os.path.join(out_dir, "agent_manifest.json")
        self.assertTrue(os.path.exists(manifest_path))
        with open(manifest_path) as f:
            manifest = json.load(f)
        self.assertIn("name", manifest)
        self.assertIn("description", manifest)
        self.assertIn("instructions", manifest)

    def test_topic_generated(self):
        result = json.loads(
            self.agent._action_transpile(agent_file=self._agent_file)
        )
        out_dir = result["output_directory"]
        topics_dir = os.path.join(out_dir, "topics")
        self.assertTrue(os.path.exists(topics_dir))
        topic_files = os.listdir(topics_dir)
        self.assertTrue(len(topic_files) > 0)

    def test_flow_generated(self):
        result = json.loads(
            self.agent._action_transpile(agent_file=self._agent_file)
        )
        out_dir = result["output_directory"]
        flows_dir = os.path.join(out_dir, "flows")
        if os.path.exists(flows_dir):
            flow_files = [f for f in os.listdir(flows_dir) if f.endswith(".json")]
            for ff in flow_files:
                with open(os.path.join(flows_dir, ff)) as f:
                    flow = json.load(f)
                self.assertIsInstance(flow, dict)

    def test_deployment_guide_generated(self):
        result = json.loads(
            self.agent._action_transpile(agent_file=self._agent_file)
        )
        out_dir = result["output_directory"]
        guide_path = os.path.join(out_dir, "DEPLOYMENT_GUIDE.md")
        self.assertTrue(os.path.exists(guide_path))

    def test_transpile_returns_file_list(self):
        result = json.loads(
            self.agent._action_transpile(agent_file=self._agent_file)
        )
        self.assertIn("files_generated", result)
        self.assertTrue(len(result["files_generated"]) > 0)

    def test_dry_run_does_not_write_files(self):
        clean_tmp = tempfile.mkdtemp()
        self.agent._transpile_dir = clean_tmp
        self.agent._action_transpile(
            agent_file=self._agent_file, dry_run=True
        )
        # Nothing should be written inside clean_tmp
        contents = []
        for _, dirs, files in os.walk(clean_tmp):
            contents.extend(files)
        self.assertEqual(len(contents), 0)
        shutil.rmtree(clean_tmp, ignore_errors=True)


# ===================================================================
# Test 5: Full Pipeline (mocked HTTP)
# ===================================================================


class TestFullPipeline(unittest.TestCase):
    """Test _action_pipeline runs all stages."""

    def setUp(self):
        self.agent = _make_agent()
        self._tmp = tempfile.mkdtemp()
        self.agent._agents_dir = self._tmp
        self.agent._transpile_dir = os.path.join(self._tmp, "transpiled")
        self.agent._data_dir = os.path.join(self._tmp, "data")

    def tearDown(self):
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _mock_urlopen(self, workflow_json):
        """Create a mock urlopen that returns workflow JSON."""
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps(workflow_json).encode()
        mock_response.__enter__ = lambda s: s
        mock_response.__exit__ = MagicMock(return_value=False)
        return mock_response

    @patch("urllib.request.urlopen")
    def test_pipeline_success_all_stages(self, mock_urlopen):
        mock_urlopen.return_value = self._mock_urlopen(MOCK_SIMPLE_WORKFLOW)
        result = json.loads(
            self.agent._action_pipeline(
                url="https://github.com/owner/repo/blob/main/flow.json",
                agent_name="PipelineTest",
                dry_run=False,
            )
        )
        self.assertIn("assimilate", result["stages"])
        self.assertIn("generate", result["stages"])
        self.assertIn("transpile", result["stages"])

    @patch("urllib.request.urlopen")
    def test_pipeline_stops_on_fetch_error(self, mock_urlopen):
        mock_urlopen.side_effect = Exception("404 Not Found")
        result = json.loads(
            self.agent._action_pipeline(
                url="https://github.com/owner/repo/blob/main/missing.json",
            )
        )
        self.assertEqual(result["status"], "error")

    @patch("urllib.request.urlopen")
    def test_pipeline_dry_run_no_files(self, mock_urlopen):
        mock_urlopen.return_value = self._mock_urlopen(MOCK_SIMPLE_WORKFLOW)
        self.agent._action_pipeline(
            url="https://github.com/owner/repo/blob/main/flow.json",
            agent_name="DryTest",
            dry_run=True,
        )
        # No agent files should be written
        py_files = [
            f
            for f in os.listdir(self._tmp)
            if f.endswith("_agent.py")
        ]
        self.assertEqual(len(py_files), 0)


# ===================================================================
# Test 6: Error Handling
# ===================================================================


class TestErrorHandling(unittest.TestCase):
    """Test graceful error handling across actions."""

    def setUp(self):
        self.agent = _make_agent()
        self._tmp = tempfile.mkdtemp()
        self.agent._data_dir = self._tmp

    def tearDown(self):
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_bad_url_format(self):
        result = json.loads(self.agent.perform(action="assimilate", url="not-a-url"))
        self.assertEqual(result["status"], "error")

    def test_missing_url_for_assimilate(self):
        result = json.loads(self.agent.perform(action="assimilate"))
        self.assertEqual(result["status"], "error")

    def test_workflow_without_nodes(self):
        result = self.agent._parse_workflow(MOCK_MALFORMED_WORKFLOW)
        self.assertEqual(result["status"], "error")

    def test_empty_workflow_nodes(self):
        result = self.agent._parse_workflow({"name": "Empty", "nodes": [], "connections": {}})
        self.assertEqual(result["node_count"], 0)

    def test_missing_action_parameter(self):
        result = json.loads(self.agent.perform())
        self.assertEqual(result["status"], "error")


# ===================================================================
# Test 7: History Persistence
# ===================================================================


class TestHistory(unittest.TestCase):
    """Test assimilation history save/load."""

    def setUp(self):
        self.agent = _make_agent()
        self._tmp = tempfile.mkdtemp()
        self.agent._data_dir = self._tmp

    def tearDown(self):
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_history_empty_initially(self):
        history = self.agent._load_history()
        self.assertEqual(history, [])

    def test_save_and_load_history(self):
        entry = {
            "timestamp": "2026-04-13T12:00:00",
            "workflow_name": "Test Flow",
            "url": "https://github.com/test/repo/blob/main/flow.json",
            "status": "success",
        }
        self.agent._save_history(entry)
        history = self.agent._load_history()
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["workflow_name"], "Test Flow")

    def test_history_action_returns_json(self):
        entry = {
            "timestamp": "2026-04-13T12:00:00",
            "workflow_name": "Test Flow",
            "url": "https://github.com/test/repo",
            "status": "success",
        }
        self.agent._save_history(entry)
        result = json.loads(self.agent._action_history())
        self.assertIn("entries", result)
        self.assertEqual(len(result["entries"]), 1)


# ===================================================================
# Test 8: Agent Loading via Brainstem
# ===================================================================


class TestAgentLoading(unittest.TestCase):
    """Test that brainstem can discover and load this agent."""

    def test_agent_instantiates(self):
        agent = _make_agent()
        self.assertEqual(agent.name, "N8nAssimilator")

    def test_agent_to_tool_schema(self):
        agent = _make_agent()
        tool = agent.to_tool()
        self.assertEqual(tool["type"], "function")
        self.assertEqual(tool["function"]["name"], "N8nAssimilator")
        params = tool["function"]["parameters"]
        self.assertIn("action", params["properties"])
        self.assertIn("url", params["properties"])
        self.assertIn("agent_name", params["properties"])
        self.assertIn("dry_run", params["properties"])


if __name__ == "__main__":
    unittest.main()
