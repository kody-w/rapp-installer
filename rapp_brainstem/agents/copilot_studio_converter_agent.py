"""
CopilotStudioConverterAgent - Converts agent.py files to native Copilot Studio solutions.

This meta-agent is the inverse of LearnNewAgent: it reads existing *_agent.py files,
uses AI to dynamically research and understand how to implement them natively in
Copilot Studio, then outputs a complete unmanaged solution zip ready for import.

LearnNewAgent: description → agent.py
CopilotStudioConverterAgent: agent.py → Copilot Studio solution
"""

import ast
import io
import json
import os
import re
import subprocess
import uuid
import zipfile
from pathlib import Path
from datetime import datetime

import sys, os; sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__)))); from basic_agent import BasicAgent


class CopilotStudioConverterAgent(BasicAgent):
    """
    Agent that converts Python agent files into native Copilot Studio solutions.

    Capabilities:
    - Read and analyze *_agent.py files via AST
    - Use AI to research how each agent's logic maps to Copilot Studio
    - Generate topic YAML, Power Automate flow JSON, GPT instructions
    - Package everything into a Dataverse-importable unmanaged solution zip
    - List available agents for conversion
    """

    # Copilot Studio topic YAML template
    TOPIC_TEMPLATE = '''kind: AdaptiveDialog
{inputs_block}
beginDialog:
  kind: OnActivity
  id: main
  type: Message
  actions:
    - kind: SetVariable
      id: setVariable_userInput
      variable: Topic.user_input
      value: =System.LastMessage.Text

{actions_block}'''

    def __init__(self):
        self.name = 'CopilotStudioConverter'
        self.metadata = {
            "name": self.name,
            "description": "Converts Python agent.py files into native Copilot Studio solutions. Feed it an agent file and it will research, analyze, and output a complete solution zip that runs natively in Copilot Studio without any external endpoints.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "description": "Action to perform.",
                        "enum": ["convert", "analyze", "list", "convert_all"]
                    },
                    "agent_file": {
                        "type": "string",
                        "description": "Path to a specific *_agent.py file to convert."
                    },
                    "agent_name": {
                        "type": "string",
                        "description": "Name of an agent in the agents/ directory to convert (e.g. 'email_drafting')."
                    },
                    "solution_name": {
                        "type": "string",
                        "description": "Name for the output solution (default: RAPPConvertedAgents)."
                    },
                    "query": {
                        "type": "string",
                        "description": "Natural language query about converting agents."
                    }
                },
                "required": []
            }
        }
        self.agents_dir = Path(__file__).parent
        self.remote_agents_dir = Path(__file__).parent.parent / '.remote_agents'
        self.output_dir = Path(__file__).parent.parent / 'rapp_projects' / 'converted_solutions'
        self.publisher_prefix = "msrnd"
        super().__init__(name=self.name, metadata=self.metadata)

    def _all_agent_dirs(self):
        """Return all directories containing agent files (local + remote)."""
        dirs = [self.agents_dir]
        if self.remote_agents_dir.exists():
            dirs.append(self.remote_agents_dir)
        return dirs

    def _find_agent_file(self, agent_file: str) -> Path:
        """Resolve an agent file path, checking all agent directories."""
        path = Path(agent_file)
        if path.exists():
            return path
        for d in self._all_agent_dirs():
            candidate = d / agent_file
            if candidate.exists():
                return candidate
            # Also try with _agent.py suffix
            if not agent_file.endswith('.py'):
                candidate = d / f"{agent_file}_agent.py"
                if candidate.exists():
                    return candidate
        return None

    def perform(self, **kwargs):
        """Convert agent.py files to Copilot Studio solutions."""
        action = kwargs.get('action', 'convert')
        agent_file = kwargs.get('agent_file', '')
        agent_name = kwargs.get('agent_name', '')
        solution_name = kwargs.get('solution_name', 'RAPPConvertedAgents')
        query = kwargs.get('query', '')

        if not agent_file and agent_name:
            # Try to find the agent file by name across all agent directories
            agent_file = f"{agent_name}_agent.py"
        if not agent_file and query:
            agent_file = query

        if action == 'list':
            return self._list_convertible_agents()
        elif action == 'analyze':
            return self._analyze_agent(agent_file)
        elif action == 'convert_all':
            return self._convert_all(solution_name)
        else:
            return self._convert_agent(agent_file, solution_name)

    # ──────────────────────────────────────────────
    # LIST — show what's available to convert
    # ──────────────────────────────────────────────

    def _list_convertible_agents(self) -> str:
        """List all agents that can be converted."""
        agents = []
        skip = {'basic_agent.py', 'copilot_studio_converter_agent.py'}
        seen = set()

        for d in self._all_agent_dirs():
            for f in sorted(d.glob('*_agent.py')):
                if f.name in skip or f.name in seen:
                    continue
                seen.add(f.name)
                manifest = self._parse_agent_file(f)
                if manifest:
                    agents.append({
                        "file": f.name,
                        "name": manifest['agent_name'],
                        "class": manifest['class_name'],
                        "description": manifest['description'][:100],
                        "category": self._classify_agent(manifest),
                    })

        return json.dumps({
            "status": "success",
            "agents": agents,
            "count": len(agents),
            "message": f"Found {len(agents)} agents ready for conversion to Copilot Studio."
        })

    # ──────────────────────────────────────────────
    # ANALYZE — research how to convert an agent
    # ──────────────────────────────────────────────

    def _analyze_agent(self, agent_file: str) -> str:
        """Analyze an agent and return the conversion plan."""
        if not agent_file:
            return json.dumps({"status": "error", "message": "Provide agent_file or agent_name."})

        path = self._find_agent_file(agent_file)
        if not path:
            return json.dumps({"status": "error", "message": f"File not found: {agent_file}"})

        manifest = self._parse_agent_file(path)
        if not manifest:
            return json.dumps({"status": "error", "message": "No BasicAgent subclass found."})

        category = self._classify_agent(manifest)
        plan = self._research_conversion(manifest, category)

        return json.dumps({
            "status": "success",
            "agent_name": manifest['agent_name'],
            "class_name": manifest['class_name'],
            "category": category,
            "description": manifest['description'],
            "parameters": list(manifest['parameters'].get('properties', {}).keys()),
            "env_vars": manifest['env_vars'],
            "conversion_plan": plan,
        })

    # ──────────────────────────────────────────────
    # CONVERT — the main event
    # ──────────────────────────────────────────────

    def _convert_agent(self, agent_file: str, solution_name: str) -> str:
        """Convert a single agent to a Copilot Studio solution."""
        if not agent_file:
            return json.dumps({"status": "error", "message": "Provide agent_file or agent_name."})

        path = self._find_agent_file(agent_file)
        if not path:
            return json.dumps({"status": "error", "message": f"File not found: {agent_file}"})

        manifest = self._parse_agent_file(path)
        if not manifest:
            return json.dumps({"status": "error", "message": "No BasicAgent subclass found."})

        category = self._classify_agent(manifest)

        # Use AI to research the best conversion approach
        plan = self._research_conversion(manifest, category)

        # Generate all Copilot Studio artifacts
        artifacts = self._generate_artifacts(manifest, category, plan)

        # Package into solution zip
        zip_bytes = self._package_solution([manifest], [artifacts], solution_name)

        # Save to disk
        self.output_dir.mkdir(parents=True, exist_ok=True)
        output_path = self.output_dir / f"{solution_name}_{manifest['agent_name']}.zip"
        output_path.write_bytes(zip_bytes)

        return json.dumps({
            "status": "success",
            "message": f"Converted {manifest['agent_name']} to Copilot Studio solution",
            "agent_name": manifest['agent_name'],
            "category": category,
            "output_path": str(output_path),
            "solution_size": len(zip_bytes),
            "artifacts_count": len(artifacts),
            "conversion_plan": plan,
            "next_steps": [
                f"Import {output_path.name} at make.powerapps.com → Solutions → Import",
                "Or run: pac solution import --path " + str(output_path),
                "Or use the VS Code Copilot Studio extension to clone → overwrite → sync"
            ]
        })

    def _convert_all(self, solution_name: str) -> str:
        """Convert all agents into a single solution."""
        skip = {'basic_agent.py', 'copilot_studio_converter_agent.py'}
        all_manifests = []
        all_artifacts = []
        seen = set()

        for d in self._all_agent_dirs():
            for f in sorted(d.glob('*_agent.py')):
                if f.name in skip or f.name in seen:
                    continue
                seen.add(f.name)
                manifest = self._parse_agent_file(f)
                if manifest:
                    category = self._classify_agent(manifest)
                    plan = self._research_conversion(manifest, category)
                    artifacts = self._generate_artifacts(manifest, category, plan)
                    all_manifests.append(manifest)
                    all_artifacts.append(artifacts)

        if not all_manifests:
            return json.dumps({"status": "error", "message": "No agents found."})

        zip_bytes = self._package_solution(all_manifests, all_artifacts, solution_name)

        self.output_dir.mkdir(parents=True, exist_ok=True)
        output_path = self.output_dir / f"{solution_name}.zip"
        output_path.write_bytes(zip_bytes)

        return json.dumps({
            "status": "success",
            "message": f"Converted {len(all_manifests)} agents to Copilot Studio solution",
            "agents": [m['agent_name'] for m in all_manifests],
            "output_path": str(output_path),
            "solution_size": len(zip_bytes),
        })

    # ──────────────────────────────────────────────
    # FETCHER — parse agent.py via AST (no execution)
    # ──────────────────────────────────────────────

    def _parse_agent_file(self, file_path: Path) -> dict:
        """Parse an agent file using AST to extract metadata without executing it."""
        try:
            source = file_path.read_text()
            tree = ast.parse(source, filename=str(file_path))
        except Exception:
            return None

        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                if any(
                    (isinstance(b, ast.Name) and b.id == 'BasicAgent') or
                    (isinstance(b, ast.Attribute) and b.attr == 'BasicAgent')
                    for b in node.bases
                ):
                    return self._extract_manifest(node, source, file_path)
        return None

    def _extract_manifest(self, class_node, source, file_path) -> dict:
        """Extract agent metadata from a class AST node."""
        agent_name = ""
        description = ""
        parameters = {}
        perform_source = ""
        env_vars = []
        imports = []

        # Get imports
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.append(alias.name)
            elif isinstance(node, ast.ImportFrom):
                imports.append(f"{node.module or ''}.{','.join(a.name for a in node.names)}")

        # Walk __init__ for self.name and self.metadata
        for node in ast.walk(class_node):
            if isinstance(node, ast.FunctionDef) and node.name == '__init__':
                for stmt in ast.walk(node):
                    if isinstance(stmt, ast.Assign):
                        for target in stmt.targets:
                            if (isinstance(target, ast.Attribute) and
                                    isinstance(target.value, ast.Name) and
                                    target.value.id == 'self'):
                                if target.attr == 'name' and isinstance(stmt.value, ast.Constant):
                                    agent_name = stmt.value.value
                                elif target.attr == 'metadata':
                                    meta_src = ast.get_source_segment(source, stmt.value)
                                    if meta_src:
                                        try:
                                            safe = meta_src.replace('self.name', repr(agent_name))
                                            meta = eval(safe, {"__builtins__": {}}, {})
                                            description = meta.get('description', '')
                                            parameters = meta.get('parameters', {})
                                        except Exception:
                                            pass

            elif isinstance(node, ast.FunctionDef) and node.name == 'perform':
                perform_source = ast.get_source_segment(source, node) or ""

        # Scan for os.environ.get
        for node in ast.walk(class_node):
            if isinstance(node, ast.Call):
                src = ast.get_source_segment(source, node) or ""
                if 'os.environ.get' in src or 'os.environ[' in src:
                    for arg in node.args:
                        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                            env_vars.append(arg.value)

        return {
            'file_path': str(file_path),
            'class_name': class_node.name,
            'agent_name': agent_name or class_node.name,
            'description': description,
            'parameters': parameters,
            'perform_source': perform_source,
            'imports': imports,
            'env_vars': env_vars,
        }

    # ──────────────────────────────────────────────
    # ANALYZER — classify + AI research
    # ──────────────────────────────────────────────

    def _classify_agent(self, manifest: dict) -> str:
        """Classify agent by pattern-matching perform() source."""
        text = (manifest['perform_source'] + " " + manifest['class_name']).lower()

        patterns = {
            'email': ['power_automate', 'email_draft', 'subject.*to.*body', 'emaildrafting'],
            'd365_crud': ['api/data/v9', 'dynamics365', 'fetchxml', 'odata-version'],
            'storage': ['storage_manager', 'read_json', 'write_json', 'set_memory_context'],
            'demo': ['scripted.*demo', 'canned.*response', 'demo_script', 'scripteddemo'],
            'api_call': [r'requests\.(post|get|patch|delete)', r'http[s]?://'],
        }

        scores = {}
        for cat, pats in patterns.items():
            score = sum(1 for p in pats if re.search(p, text))
            if score:
                scores[cat] = score

        return max(scores, key=scores.get) if scores else 'composite'

    def _research_conversion(self, manifest: dict, category: str) -> dict:
        """Use AI to research how this agent should be implemented in Copilot Studio."""
        # Build a research prompt
        prompt = f"""I have a Python agent that needs to be converted to a NATIVE Copilot Studio solution.

Agent: {manifest['agent_name']}
Description: {manifest['description']}
Category: {category}
Parameters: {json.dumps(list(manifest['parameters'].get('properties', {}).keys()))}
Environment vars: {manifest['env_vars']}
Perform method:
{manifest['perform_source'][:1500]}

How should this be implemented natively in Copilot Studio? Reply with JSON only:
{{
  "native_connector": "which Power Platform connector replaces the Python logic",
  "topic_type": "how to structure the Copilot Studio topic",
  "flow_needed": true/false,
  "flow_description": "what the Power Automate flow should do",
  "gpt_instructions": "what to tell the GPT orchestrator about this agent",
  "connection_references": ["list of connector API names needed"],
  "notes": "any special considerations"
}}"""

        try:
            result = subprocess.run(
                ['copilot', '--message', prompt],
                capture_output=True, text=True, timeout=30
            )
            if result.returncode == 0 and result.stdout.strip():
                output = result.stdout.strip()
                # Extract JSON from response
                match = re.search(r'\{.*\}', output, re.DOTALL)
                if match:
                    return json.loads(match.group())
        except Exception:
            pass

        # Fallback: static mapping based on category
        return self._static_conversion_plan(manifest, category)

    def _static_conversion_plan(self, manifest: dict, category: str) -> dict:
        """Fallback conversion plan when AI isn't available."""
        plans = {
            'email': {
                "native_connector": "Office 365 Outlook (shared_office365)",
                "topic_type": "Invoke Power Automate flow with email parameters",
                "flow_needed": True,
                "flow_description": "Send email using native Office 365 connector SendEmailV2 action",
                "gpt_instructions": f"Route to this topic when user wants to: {manifest['description'][:150]}",
                "connection_references": ["shared_office365"],
                "notes": "Replaces HTTP webhook to Power Automate with native Office 365 connector"
            },
            'd365_crud': {
                "native_connector": "Dataverse (shared_commondataserviceforapps)",
                "topic_type": "Invoke Power Automate flow with CRUD parameters",
                "flow_needed": True,
                "flow_description": "Perform Dataverse CRUD operations using native connector — no OAuth needed",
                "gpt_instructions": f"Route to this topic when user wants to: {manifest['description'][:150]}",
                "connection_references": ["shared_commondataserviceforapps"],
                "notes": "Replaces HTTP+OAuth to D365 Web API with native Dataverse connector"
            },
            'storage': {
                "native_connector": "Dataverse (shared_commondataserviceforapps)",
                "topic_type": "Invoke Power Automate flow to read/write Annotations",
                "flow_needed": True,
                "flow_description": "Read/write memories as Dataverse Annotations with subject prefix rapp:memory:",
                "gpt_instructions": f"Route to this topic when user wants to: {manifest['description'][:150]}",
                "connection_references": ["shared_commondataserviceforapps"],
                "notes": "Replaces storage_manager with native Dataverse Annotations"
            },
            'demo': {
                "native_connector": "None — topic-only with conditional branching",
                "topic_type": "Topic with ConditionGroup actions and canned SendActivity responses",
                "flow_needed": False,
                "flow_description": "",
                "gpt_instructions": f"Route to this topic when user wants to: {manifest['description'][:150]}",
                "connection_references": [],
                "notes": "Scripted demo converted to YAML topic with conditional branching"
            },
        }
        return plans.get(category, {
            "native_connector": "HTTP connector (shared_http) or custom connector",
            "topic_type": "Invoke Power Automate flow with HTTP action",
            "flow_needed": True,
            "flow_description": "Generic HTTP action calling external API",
            "gpt_instructions": f"Route to this topic when user wants to: {manifest['description'][:150]}",
            "connection_references": [],
            "notes": "Generic API agent — may need custom connector for full native conversion"
        })

    # ──────────────────────────────────────────────
    # NORMALIZER — generate Copilot Studio artifacts
    # ──────────────────────────────────────────────

    def _generate_artifacts(self, manifest: dict, category: str, plan: dict) -> list:
        """Generate all Copilot Studio solution artifacts for an agent."""
        safe_name = re.sub(r'[^a-zA-Z0-9]', '', manifest['agent_name'])
        bot_schema = f"{self.publisher_prefix}_{safe_name}"
        artifacts = []

        # Main topic
        artifacts.append(self._gen_main_topic(manifest, bot_schema, plan))
        # GPT instructions
        artifacts.append(self._gen_gpt_config(manifest, bot_schema, plan))
        # Standard system topics
        artifacts += self._gen_standard_topics(bot_schema)
        # Power Automate flow (if needed)
        if plan.get('flow_needed', False):
            artifacts.append(self._gen_flow(manifest, bot_schema, category, plan))
        # Bot config + bot.xml
        artifacts.append(self._gen_bot_config(bot_schema))
        artifacts.append(self._gen_bot_xml(manifest, bot_schema))
        # botcomponent.xml for each topic/gpt
        for a in list(artifacts):
            if a['type'] in ('topic', 'gpt'):
                artifacts.append(self._gen_botcomponent_xml(a))

        return artifacts

    def _gen_main_topic(self, manifest, bot_schema, plan) -> dict:
        """Generate the main topic YAML — uses AI if available."""
        params = manifest['parameters'].get('properties', {})

        # Try AI-generated topic
        topic_yaml = self._ai_generate_topic(manifest, plan)
        if not topic_yaml:
            topic_yaml = self._static_generate_topic(manifest, params, plan)

        return {
            'path': f"botcomponents/{bot_schema}.topic.MAIN/data",
            'content': topic_yaml,
            'type': 'topic',
        }

    def _ai_generate_topic(self, manifest, plan) -> str:
        """Use AI to generate the topic YAML."""
        try:
            prompt = f"""Generate a Copilot Studio topic YAML (AdaptiveDialog format) for an agent that: {manifest['description'][:300]}

Parameters: {json.dumps(list(manifest['parameters'].get('properties', {}).keys()))}
Conversion plan: {json.dumps(plan)}

The YAML must use kind: AdaptiveDialog with beginDialog, OnActivity, and actions.
Use SetVariable, InvokeFlowAction, ConditionGroup, SendActivity as needed.
Return ONLY the YAML, no markdown fences."""

            result = subprocess.run(
                ['copilot', '--message', prompt],
                capture_output=True, text=True, timeout=30
            )
            if result.returncode == 0:
                output = result.stdout.strip()
                if '```' in output:
                    output = output.split('```')[1].split('```')[0]
                    if output.startswith('yaml'):
                        output = output[4:]
                if 'kind: AdaptiveDialog' in output:
                    return output.strip()
        except Exception:
            pass
        return None

    def _static_generate_topic(self, manifest, params, plan) -> str:
        """Fallback static topic generation."""
        inputs = ""
        if params:
            input_items = []
            for pname, pdef in params.items():
                desc = pdef.get('description', pname)
                input_items.append(f"""  - kind: AutomaticTaskInput
    propertyName: {pname}
    entity: StringPrebuiltEntity
    shouldPromptUser: false
    modelDescription: "{desc}"
""")
            inputs = "inputs:\n" + "\n".join(input_items)

        if plan.get('flow_needed'):
            flow_id = str(uuid.uuid4())
            param_keys = list(params.keys()) if params else ['user_input']
            bindings = "\n".join(f"          {k}: =Topic.{k}" for k in param_keys)
            actions = f"""    - kind: InvokeFlowAction
      id: invokeFlow_main
      input:
        binding:
{bindings}
      output:
        binding:
          output: Topic.result
      flowId: {flow_id}

    - kind: SendActivity
      id: sendActivity_result
      activity: "{{Topic.result}}"
"""
        else:
            actions = """    - kind: SendActivity
      id: sendActivity_result
      activity: "{Topic.user_input}"
"""

        return self.TOPIC_TEMPLATE.format(
            inputs_block=inputs,
            actions_block=actions,
        )

    def _gen_gpt_config(self, manifest, bot_schema, plan) -> dict:
        instructions = plan.get('gpt_instructions', manifest['description'])
        params = manifest['parameters'].get('properties', {})
        if params:
            param_lines = "\n".join(f"  - {k}: {v.get('description', k)}" for k, v in params.items())
            instructions += f"\n\nParameters to extract from user message:\n{param_lines}"

        return {
            'path': f"botcomponents/{bot_schema}.gpt.default/data",
            'content': f'kind: Copilot\ndescription: "{instructions}"\n',
            'type': 'gpt',
        }

    def _gen_standard_topics(self, bot_schema) -> list:
        topics = {
            'Greeting': ('OnRecognizedIntent', 'Greeting', "Hello! How can I help you today?"),
            'Fallback': ('OnUnknownIntent', None, "I'm sorry, I didn't understand. Could you try rephrasing?"),
            'Goodbye': ('OnRecognizedIntent', 'Goodbye', "Goodbye! Have a great day."),
            'Escalate': ('OnRecognizedIntent', 'Escalate', "Let me connect you with a human agent."),
            'ThankYou': ('OnRecognizedIntent', 'ThankYou', "You're welcome!"),
        }
        result = []
        for name, (kind, intent, msg) in topics.items():
            intent_line = f"\n  intent: {intent}" if intent else ""
            yaml = f"""kind: AdaptiveDialog
beginDialog:
  kind: {kind}
  id: main{intent_line}
  actions:
    - kind: SendActivity
      id: sendActivity_{name.lower()}
      activity: "{msg}"
"""
            result.append({
                'path': f"botcomponents/{bot_schema}.topic.{name}/data",
                'content': yaml,
                'type': 'topic',
            })
        return result

    def _gen_flow(self, manifest, bot_schema, category, plan) -> dict:
        """Generate Power Automate flow JSON based on category."""
        flow_guid = str(uuid.uuid4())
        connectors = plan.get('connection_references', [])

        if category == 'email':
            flow = self._flow_email(manifest, flow_guid, connectors)
        elif category in ('d365_crud', 'storage'):
            flow = self._flow_dataverse(manifest, flow_guid, connectors, category)
        else:
            flow = self._flow_http(manifest, flow_guid)

        safe = re.sub(r'[^a-zA-Z0-9]', '', manifest['agent_name'])
        return {
            'path': f"Workflows/{safe}-{flow_guid.upper()}.json",
            'content': json.dumps(flow, indent=2),
            'type': 'flow',
            'flow_guid': flow_guid,
            'flow_name': f"{manifest['agent_name']} Action",
        }

    def _flow_email(self, manifest, guid, connectors) -> dict:
        conn_ref = f"{self.publisher_prefix}_sharedoffice365_{guid[:5]}"
        return {
            "properties": {
                "connectionReferences": {
                    "shared_office365": {
                        "runtimeSource": "invoker",
                        "connection": {"connectionReferenceLogicalName": conn_ref},
                        "api": {"name": "shared_office365"}
                    }
                },
                "definition": {
                    "$schema": "https://schema.management.azure.com/providers/Microsoft.Logic/schemas/2016-06-01/workflowdefinition.json#",
                    "contentVersion": "1.0.0.0",
                    "parameters": {
                        "$connections": {"defaultValue": {}, "type": "Object"},
                        "$authentication": {"defaultValue": {}, "type": "SecureObject"}
                    },
                    "triggers": {"manual": {
                        "type": "Request", "kind": "Skills",
                        "inputs": {"schema": {"type": "object", "properties": {
                            "subject": {"title": "subject", "type": "string"},
                            "to": {"title": "to", "type": "string"},
                            "body": {"title": "body", "type": "string"},
                        }, "required": ["subject", "to", "body"]}}
                    }},
                    "actions": {
                        "Send_an_email_(V2)": {
                            "runAfter": {},
                            "type": "OpenApiConnection",
                            "inputs": {
                                "host": {"connectionName": "shared_office365", "operationId": "SendEmailV2", "apiId": "/providers/Microsoft.PowerApps/apis/shared_office365"},
                                "parameters": {
                                    "emailMessage/To": "@triggerBody()['to']",
                                    "emailMessage/Subject": "@triggerBody()['subject']",
                                    "emailMessage/Body": "@triggerBody()['body']",
                                },
                                "authentication": "@parameters('$authentication')"
                            }
                        },
                        "Respond_to_Copilot": {
                            "runAfter": {"Send_an_email_(V2)": ["Succeeded"]},
                            "type": "Response", "kind": "Skills",
                            "inputs": {"statusCode": 200, "body": {"output": "Email sent successfully to @{triggerBody()['to']}"}, "schema": {"type": "object", "properties": {"output": {"title": "output", "type": "string"}}}}
                        }
                    }
                }
            },
            "schemaVersion": "1.0.0.0"
        }

    def _flow_dataverse(self, manifest, guid, connectors, category) -> dict:
        conn_ref = f"{self.publisher_prefix}_shareddataverse_{guid[:5]}"
        entity = "annotations" if category == 'storage' else "@triggerBody()?['entity']"
        return {
            "properties": {
                "connectionReferences": {
                    "shared_commondataserviceforapps": {
                        "runtimeSource": "invoker",
                        "connection": {"connectionReferenceLogicalName": conn_ref},
                        "api": {"name": "shared_commondataserviceforapps"}
                    }
                },
                "definition": {
                    "$schema": "https://schema.management.azure.com/providers/Microsoft.Logic/schemas/2016-06-01/workflowdefinition.json#",
                    "contentVersion": "1.0.0.0",
                    "parameters": {
                        "$connections": {"defaultValue": {}, "type": "Object"},
                        "$authentication": {"defaultValue": {}, "type": "SecureObject"}
                    },
                    "triggers": {"manual": {
                        "type": "Request", "kind": "Skills",
                        "inputs": {"schema": {"type": "object", "properties": {
                            "operation": {"title": "operation", "type": "string"},
                            "entity": {"title": "entity", "type": "string"},
                            "data": {"title": "data", "type": "string"},
                            "record_id": {"title": "record_id", "type": "string"},
                        }, "required": ["operation"]}}
                    }},
                    "actions": {
                        "List_Records": {
                            "runAfter": {},
                            "type": "OpenApiConnection",
                            "inputs": {
                                "host": {"connectionName": "shared_commondataserviceforapps", "operationId": "ListRecords", "apiId": "/providers/Microsoft.PowerApps/apis/shared_commondataserviceforapps"},
                                "parameters": {"entityName": entity},
                                "authentication": "@parameters('$authentication')"
                            }
                        },
                        "Respond_to_Copilot": {
                            "runAfter": {"List_Records": ["Succeeded"]},
                            "type": "Response", "kind": "Skills",
                            "inputs": {"statusCode": 200, "body": {"output": "@{body('List_Records')}"}, "schema": {"type": "object", "properties": {"output": {"title": "output", "type": "string"}}}}
                        }
                    }
                }
            },
            "schemaVersion": "1.0.0.0"
        }

    def _flow_http(self, manifest, guid) -> dict:
        return {
            "properties": {
                "definition": {
                    "$schema": "https://schema.management.azure.com/providers/Microsoft.Logic/schemas/2016-06-01/workflowdefinition.json#",
                    "contentVersion": "1.0.0.0",
                    "parameters": {"$authentication": {"defaultValue": {}, "type": "SecureObject"}},
                    "triggers": {"manual": {
                        "type": "Request", "kind": "Skills",
                        "inputs": {"schema": {"type": "object", "properties": {"user_input": {"title": "user_input", "type": "string"}}, "required": ["user_input"]}}
                    }},
                    "actions": {
                        "HTTP": {"runAfter": {}, "type": "Http", "inputs": {"method": "POST", "uri": "@parameters('api_url')", "headers": {"Content-Type": "application/json"}, "body": {"input": "@triggerBody()['user_input']"}}},
                        "Respond_to_Copilot": {"runAfter": {"HTTP": ["Succeeded"]}, "type": "Response", "kind": "Skills", "inputs": {"statusCode": 200, "body": {"output": "@body('HTTP')"}, "schema": {"type": "object", "properties": {"output": {"title": "output", "type": "string"}}}}}
                    }
                }
            },
            "schemaVersion": "1.0.0.0"
        }

    def _gen_bot_config(self, bot_schema) -> dict:
        return {
            'path': f"bots/{bot_schema}/configuration.json",
            'content': json.dumps({
                "$kind": "BotConfiguration",
                "channels": [{"$kind": "ChannelDefinition", "channelId": "MsTeams"}, {"$kind": "ChannelDefinition", "channelId": "Microsoft365Copilot"}],
                "publishOnImport": True,
                "gPTSettings": {"$kind": "GPTSettings", "defaultSchemaName": f"{bot_schema}.gpt.default"},
                "isLightweightBot": False,
                "aISettings": {"$kind": "AISettings", "useModelKnowledge": True, "isSemanticSearchEnabled": True, "optInUseLatestModels": False},
            }, indent=2),
            'type': 'bot_config',
        }

    def _gen_bot_xml(self, manifest, bot_schema) -> dict:
        desc = manifest['description'][:200].replace('"', '&quot;')
        return {
            'path': f"bots/{bot_schema}/bot.xml",
            'content': f'''<?xml version="1.0" encoding="utf-8"?>
<bot botId="{{{uuid.uuid4()}}}" name="{bot_schema}" displayName="{manifest['agent_name']}" description="{desc}" schemaName="{bot_schema}">
  <Topics>
    <Topic schemaName="{bot_schema}.topic.MAIN" />
    <Topic schemaName="{bot_schema}.topic.Greeting" />
    <Topic schemaName="{bot_schema}.topic.Fallback" />
    <Topic schemaName="{bot_schema}.topic.Goodbye" />
    <Topic schemaName="{bot_schema}.topic.Escalate" />
    <Topic schemaName="{bot_schema}.topic.ThankYou" />
  </Topics>
  <GPTConfigs><GPTConfig schemaName="{bot_schema}.gpt.default" /></GPTConfigs>
</bot>''',
            'type': 'bot_xml',
        }

    def _gen_botcomponent_xml(self, artifact) -> dict:
        parts = artifact['path'].split('/')
        component = parts[1] if len(parts) > 1 else "unknown"
        return {
            'path': f"{'/'.join(parts[:-1])}/botcomponent.xml",
            'content': f'<?xml version="1.0" encoding="utf-8"?>\n<BotComponent botComponentId="{{{uuid.uuid4()}}}" schemaName="{component}" />',
            'type': 'botcomponent_xml',
        }

    # ──────────────────────────────────────────────
    # PACKAGER — build solution zip
    # ──────────────────────────────────────────────

    def _package_solution(self, manifests, all_artifacts, solution_name) -> bytes:
        """Package artifacts into a Dataverse-importable solution zip."""
        buf = io.BytesIO()

        # Collect flow metadata for solution.xml
        all_flows = []
        for artifacts in all_artifacts:
            for a in artifacts:
                if a['type'] == 'flow':
                    all_flows.append(a)

        with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("solution.xml", self._solution_xml(solution_name, all_flows))
            zf.writestr("customizations.xml", self._customizations_xml(all_artifacts, all_flows))
            zf.writestr("[Content_Types].xml", '<?xml version="1.0" encoding="utf-8"?>\n<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="xml" ContentType="application/xml" /><Default Extension="json" ContentType="application/json" /></Types>')

            for artifacts in all_artifacts:
                for a in artifacts:
                    zf.writestr(a['path'], a['content'])

        return buf.getvalue()

    def _solution_xml(self, solution_name, flows) -> str:
        root_components = "\n".join(
            f'      <RootComponent type="29" id="{{{f["flow_guid"]}}}" behavior="0" />'
            for f in flows
        )
        return f'''<?xml version="1.0" encoding="utf-8"?>
<ImportExportXml version="9.2.25114.191" SolutionPackageVersion="9.2" languagecode="1033" generatedBy="CopilotStudioConverterAgent" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <SolutionManifest>
    <UniqueName>{solution_name}</UniqueName>
    <LocalizedNames><LocalizedName description="{solution_name}" languagecode="1033" /></LocalizedNames>
    <Version>1.0.0.1</Version>
    <Managed>0</Managed>
    <Publisher>
      <UniqueName>Microsoft_Research_and_Development</UniqueName>
      <LocalizedNames><LocalizedName description="Microsoft Research and Development" languagecode="1033" /></LocalizedNames>
      <CustomizationPrefix>{self.publisher_prefix}</CustomizationPrefix>
      <CustomizationOptionValuePrefix>55058</CustomizationOptionValuePrefix>
      <Addresses><Address><AddressNumber>1</AddressNumber><AddressTypeCode>1</AddressTypeCode></Address></Addresses>
    </Publisher>
    <RootComponents>
{root_components}
    </RootComponents>
    <MissingDependencies />
  </SolutionManifest>
</ImportExportXml>'''

    def _customizations_xml(self, all_artifacts, flows) -> str:
        workflows = ""
        conn_refs = ""
        seen = set()

        for f in flows:
            workflows += f'''    <Workflow WorkflowId="{{{f['flow_guid']}}}" Name="{f.get('flow_name', 'Action')}">
      <JsonFileName>/{f['path']}</JsonFileName>
      <Type>1</Type><Category>5</Category><StateCode>1</StateCode><StatusCode>2</StatusCode>
      <RunAs>1</RunAs><IsTransacted>1</IsTransacted><Managed>0</Managed><PrimaryEntity>none</PrimaryEntity>
    </Workflow>
'''
            # Extract connection refs from flow content
            try:
                flow_json = json.loads(f['content'])
                for cname, cdef in flow_json.get('properties', {}).get('connectionReferences', {}).items():
                    logical = cdef.get('connection', {}).get('connectionReferenceLogicalName', '')
                    api = cdef.get('api', {}).get('name', cname)
                    if logical and logical not in seen:
                        seen.add(logical)
                        conn_refs += f'    <connectionreference connectionreferencelogicalname="{logical}"><connectorid>/providers/Microsoft.PowerApps/apis/{api}</connectorid><iscustomizable>1</iscustomizable><statecode>0</statecode><statuscode>1</statuscode></connectionreference>\n'
            except Exception:
                pass

        return f'''<?xml version="1.0" encoding="utf-8"?>
<ImportExportXml xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <Entities /><Roles />
  <Workflows>
{workflows}  </Workflows>
  <connectionreferences>
{conn_refs}  </connectionreferences>
  <Languages><Language>1033</Language></Languages>
</ImportExportXml>'''
