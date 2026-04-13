#!/usr/bin/env python3
"""
Build a Power Platform solution .zip from transpiled Copilot Studio agent files.

Reads:
  - agent_manifest.json
  - connectors.json
  - topics/topic_*.json
  - flows/flow_*.json

Produces:
  - DailySalesReport_1_0_0_0.zip  (importable via `pac solution import`)
"""

import json
import os
import uuid
import random
import string
import zipfile
from pathlib import Path

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
SCRIPT_DIR = Path(__file__).resolve().parent
OUTPUT_ZIP = SCRIPT_DIR / "DailySalesReport_1_0_0_0.zip"

SOLUTION_UNIQUE_NAME = "DailySalesReport"
SOLUTION_DISPLAY_NAME = "Daily Sales Report Agent"
SOLUTION_VERSION = "1.0.0.0"

PUBLISHER_UNIQUE_NAME = "RAPPPublisher"
PUBLISHER_DISPLAY_NAME = "RAPP Publisher"
PUBLISHER_DESCRIPTION = "RAPP Agent Publisher"
PUBLISHER_PREFIX = "rapp"
PUBLISHER_OPTION_VALUE_PREFIX = "10000"

BOT_NAME = "Daily Sales Report"
BOT_LANGUAGE = 1033
BOT_TEMPLATE = "default-2.1.0"


def generate_short_suffix(length=6):
    """Generate a random alphanumeric suffix like 'L4Y3ee'."""
    chars = string.ascii_letters + string.digits
    return "".join(random.choice(chars) for _ in range(length))


def guid():
    """Return a new lowercase GUID string (no braces)."""
    return str(uuid.uuid4()).lower()


def braced_guid(g):
    return "{" + g + "}"


def upper_guid(g):
    return g.upper()


# ---------------------------------------------------------------------------
# Read transpiled files
# ---------------------------------------------------------------------------
def load_json(path):
    with open(path, "r") as f:
        return json.load(f)


manifest = load_json(SCRIPT_DIR / "agent_manifest.json")
connectors = load_json(SCRIPT_DIR / "connectors.json")

topic_files = sorted((SCRIPT_DIR / "topics").glob("topic_*.json"))
flow_files = sorted((SCRIPT_DIR / "flows").glob("flow_*.json"))

topics = {tf.stem: load_json(tf) for tf in topic_files}
flows = {ff.stem: load_json(ff) for ff in flow_files}

# ---------------------------------------------------------------------------
# Generate stable identifiers
# ---------------------------------------------------------------------------
SCHEMA_SUFFIX = generate_short_suffix()
SCHEMA_NAME = f"{PUBLISHER_PREFIX}_{SOLUTION_UNIQUE_NAME.lower()}_{SCHEMA_SUFFIX}"

# Generate GUIDs for each flow (workflow)
flow_guids = {}
for flow_name in flows:
    flow_guids[flow_name] = guid()

# Map flow logical names to their GUIDs (for topic InvokeFlowAction references)
flow_name_to_guid = {}
for flow_name, flow_data in flows.items():
    flow_name_to_guid[flow_data["name"]] = flow_guids[flow_name]

# Connection reference logical names
conn_ref_names = {}
for key, conn in connectors["connectors"].items():
    suffix = guid()[:5]
    conn_ref_names[key] = f"{PUBLISHER_PREFIX}_{conn['connectorId']}_{suffix}"


# ---------------------------------------------------------------------------
# System topic definitions
# ---------------------------------------------------------------------------
SYSTEM_TOPICS = {
    "ConversationStart": {
        "name": "Conversation Start",
        "description": "This system topic triggers when the agent receives an Activity indicating the beginning of a new conversation.",
        "statecode": "0",
        "statuscode": "1",
        "data": f"""kind: AdaptiveDialog
beginDialog:
  kind: OnConversationStart
  id: main
  actions:
    - kind: SendActivity
      id: sendMessage_welcome
      activity:
        text:
          - |-
            Hi! I'm {{{{System.Bot.Name}}}}, your Daily Sales Report assistant. I can help you:
            - Read sales data from Excel
            - Generate daily sales reports
            - Send reports via email

            What would you like to do?
"""
    },
    "Escalate": {
        "name": "Escalate",
        "description": "This system topic is triggered when the user indicates they would like to speak to a representative.",
        "statecode": "1",
        "statuscode": "2",
        "data": f"""kind: AdaptiveDialog
startBehavior: CancelOtherTopics
beginDialog:
  kind: OnEscalate
  id: main
  intent:
    displayName: Escalate
    includeInOnSelectIntent: false
    triggerQueries:
      - Talk to agent
      - Talk to a person
      - Talk to someone
      - Can I speak to a representative
      - I need help from a person
      - Connect me to a live agent

  actions:
    - kind: SendActivity
      id: sendMessage_escalate
      conversationOutcome: Escalated
      activity: |-
        Escalating to a representative is not currently configured for this agent. Is there anything else I can help you with?
"""
    },
    "EndofConversation": {
        "name": "End of Conversation",
        "description": "This system topic is only triggered by a redirect action, and guides the user through rating their conversation with the agent.",
        "statecode": "1",
        "statuscode": "2",
        "data": f"""kind: AdaptiveDialog
startBehavior: CancelOtherTopics
beginDialog:
  kind: OnSystemRedirect
  id: main
  actions:
    - kind: Question
      id: surveyQuestion
      conversationOutcome: ResolvedImplied
      alwaysPrompt: true
      variable: init:Topic.SurveyResponse
      prompt: Did that answer your question?
      entity: BooleanPrebuiltEntity

    - kind: ConditionGroup
      id: condition_survey
      conditions:
        - id: condition_yes
          condition: =Topic.SurveyResponse = true
          actions:
            - kind: SendActivity
              id: sendMessage_thanks
              activity: Thanks for your feedback.

      elseActions:
        - kind: BeginDialog
          id: escalate_redirect
          dialog: {SCHEMA_NAME}.topic.Escalate
"""
    },
    "Fallback": {
        "name": "Fallback",
        "description": "This system topic triggers when the user's utterance does not match any existing topics.",
        "statecode": "1",
        "statuscode": "2",
        "data": f"""kind: AdaptiveDialog
beginDialog:
  kind: OnUnknownIntent
  id: main
  actions:
    - kind: ConditionGroup
      id: conditionGroup_fallback
      conditions:
        - id: conditionItem_retry
          condition: =System.FallbackCount < 3
          actions:
            - kind: SendActivity
              id: sendMessage_retry
              activity: I'm sorry, I'm not sure how to help with that. Can you try rephrasing?

      elseActions:
        - kind: BeginDialog
          id: escalate_fallback
          dialog: {SCHEMA_NAME}.topic.Escalate
"""
    },
    "Goodbye": {
        "name": "Goodbye",
        "description": "This topic triggers when the user says goodbye.",
        "statecode": "1",
        "statuscode": "2",
        "data": f"""kind: AdaptiveDialog
startBehavior: CancelOtherTopics
beginDialog:
  kind: OnRecognizedIntent
  id: main
  intent:
    displayName: Goodbye
    includeInOnSelectIntent: false
    triggerQueries:
      - Bye
      - Bye for now
      - Good bye
      - See you later

  actions:
    - kind: Question
      id: question_end
      variable: Topic.EndConversation
      prompt: Would you like to end our conversation?
      entity: BooleanPrebuiltEntity

    - kind: ConditionGroup
      id: condition_end
      conditions:
        - id: condition_end_yes
          condition: =Topic.EndConversation = true
          actions:
            - kind: BeginDialog
              id: redirect_eoc
              dialog: {SCHEMA_NAME}.topic.EndofConversation

        - id: condition_end_no
          condition: =Topic.EndConversation = false
          actions:
            - kind: SendActivity
              id: sendMessage_continue
              activity: Go ahead. I'm listening.
"""
    },
    "Greeting": {
        "name": "Greeting",
        "description": "This topic is triggered when the user greets the agent.",
        "statecode": "1",
        "statuscode": "2",
        "data": f"""kind: AdaptiveDialog
beginDialog:
  kind: OnRecognizedIntent
  id: main
  intent:
    displayName: Greeting
    includeInOnSelectIntent: false
    triggerQueries:
      - Good afternoon
      - Good morning
      - Hello
      - Hey
      - Hi

  actions:
    - kind: SendActivity
      id: sendMessage_greeting
      activity: Hello! How can I help you with sales reports today?
"""
    },
    "MultipleTopicsMatched": {
        "name": "Multiple Topics Matched",
        "description": "This system topic triggers when the agent matches multiple Topics with the incoming message.",
        "statecode": "1",
        "statuscode": "2",
        "data": f"""kind: AdaptiveDialog
beginDialog:
  kind: OnSelectIntent
  id: main
  triggerBehavior: Always
  actions:
    - kind: SetVariable
      id: setVariable_options
      variable: init:Topic.IntentOptions
      value: =System.Recognizer.IntentOptions

    - kind: SetTextVariable
      id: setTextVariable_none
      variable: Topic.NoneOfTheseDisplayName
      value: None of these

    - kind: EditTable
      id: addNoneOption
      changeType: Add
      itemsVariable: Topic.IntentOptions
      value: "={{{{ DisplayName: Topic.NoneOfTheseDisplayName, TopicId: \\"NoTopic\\", TriggerId: \\"NoTrigger\\", Score: 1.0 }}}}"

    - kind: Question
      id: question_clarify
      interruptionPolicy:
        allowInterruption: false
      alwaysPrompt: true
      variable: System.Recognizer.SelectedIntent
      prompt: "To clarify, did you mean:"
      entity:
        kind: DynamicClosedListEntity
        items: =Topic.IntentOptions

    - kind: ConditionGroup
      id: conditionGroup_selected
      conditions:
        - id: conditionItem_none
          condition: =System.Recognizer.SelectedIntent.TopicId = "NoTopic"
          actions:
            - kind: ReplaceDialog
              id: redirect_fallback
              dialog: {SCHEMA_NAME}.topic.Fallback
"""
    },
    "OnError": {
        "name": "On Error",
        "description": "This system topic triggers when the agent encounters an error.",
        "statecode": "1",
        "statuscode": "2",
        "data": f"""kind: AdaptiveDialog
startBehavior: UseLatestPublishedContentAndCancelOtherTopics
beginDialog:
  kind: OnError
  id: main
  actions:
    - kind: SetVariable
      id: setVariable_timestamp
      variable: init:Topic.CurrentTime
      value: =Text(Now(), DateTimeFormat.UTC)

    - kind: SendActivity
      id: sendMessage_error
      activity:
        text:
          - |-
            An error has occurred.
            Error code: {{{{System.Error.Code}}}}
            Conversation Id: {{{{System.Conversation.Id}}}}
            Time (UTC): {{{{Topic.CurrentTime}}}}.
        speak:
          - An error has occurred, please try again.

    - kind: CancelAllDialogs
      id: cancelAll
"""
    },
    "ResetConversation": {
        "name": "Reset Conversation",
        "description": "",
        "statecode": "1",
        "statuscode": "2",
        "data": f"""kind: AdaptiveDialog
startBehavior: UseLatestPublishedContentAndCancelOtherTopics
beginDialog:
  kind: OnSystemRedirect
  id: main
  actions:
    - kind: SendActivity
      id: sendMessage_reset
      activity: What can I help you with?

    - kind: ClearAllVariables
      id: clearAllVariables_reset
      variables: ConversationScopedVariables

    - kind: CancelAllDialogs
      id: cancelAllDialogs_reset
"""
    },
    "Search": {
        "name": "Conversational boosting",
        "description": "Create generative answers from knowledge sources.",
        "statecode": "1",
        "statuscode": "2",
        "data": """kind: AdaptiveDialog
beginDialog:
  kind: OnUnknownIntent
  id: main
  priority: -1
  actions:
    - kind: SearchAndSummarizeContent
      id: search-content
      variable: Topic.Answer
      userInput: =System.Activity.Text

    - kind: ConditionGroup
      id: has-answer-conditions
      conditions:
        - id: has-answer
          condition: =!IsBlank(Topic.Answer)
          actions:
            - kind: EndDialog
              id: end-topic
              clearTopicQueue: true
"""
    },
    "Signin": {
        "name": "Sign in",
        "description": "This system topic triggers when the agent needs to sign in the user.",
        "statecode": "1",
        "statuscode": "2",
        "data": """kind: AdaptiveDialog
beginDialog:
  kind: OnSignIn
  id: main
  actions:
    - kind: ConditionGroup
      id: conditionGroup_signin
      conditions:
        - id: conditionItem_required
          condition: =System.SignInReason = SignInReason.SignInRequired
          actions:
            - kind: SendActivity
              id: sendMessage_signin
              activity: Hello! To be able to help you, I'll need you to sign in.

    - kind: OAuthInput
      id: oauthInput
      title: Login
      text: To continue, please login
"""
    },
    "StartOver": {
        "name": "Start Over",
        "description": "",
        "statecode": "1",
        "statuscode": "2",
        "data": f"""kind: AdaptiveDialog
beginDialog:
  kind: OnRecognizedIntent
  id: main
  intent:
    displayName: Start Over
    includeInOnSelectIntent: false
    triggerQueries:
      - let's begin again
      - start over
      - start again
      - restart

  actions:
    - kind: Question
      id: question_confirm
      alwaysPrompt: false
      variable: init:Topic.Confirm
      prompt: Are you sure you want to restart the conversation?
      entity: BooleanPrebuiltEntity

    - kind: ConditionGroup
      id: conditionGroup_confirm
      conditions:
        - id: conditionItem_yes
          condition: =Topic.Confirm = true
          actions:
            - kind: BeginDialog
              id: redirect_reset
              dialog: {SCHEMA_NAME}.topic.ResetConversation

      elseActions:
        - kind: SendActivity
          id: sendMessage_carry_on
          activity: Ok. Let's carry on.
"""
    },
    "ThankYou": {
        "name": "Thank you",
        "description": "This topic triggers when the user says thank you.",
        "statecode": "1",
        "statuscode": "2",
        "data": """kind: AdaptiveDialog
beginDialog:
  kind: OnRecognizedIntent
  id: main
  intent:
    displayName: Thank you
    includeInOnSelectIntent: false
    triggerQueries:
      - thanks
      - thank you
      - thanks so much
      - ty

  actions:
    - kind: SendActivity
      id: sendMessage_thanks
      activity: You're welcome.
"""
    },
}


# ---------------------------------------------------------------------------
# Build custom topic YAML from transpiled JSON
# ---------------------------------------------------------------------------
def build_topic_yaml(topic_json, flow_name_to_guid_map):
    """Convert transpiled topic JSON to Copilot Studio AdaptiveDialog YAML."""
    lines = []
    lines.append("kind: AdaptiveDialog")
    lines.append("beginDialog:")
    lines.append("  kind: OnRecognizedIntent")
    lines.append("  id: main")
    lines.append("  intent:")
    lines.append(f"    displayName: {topic_json['displayName']}")

    if topic_json.get("triggers"):
        trigger = topic_json["triggers"][0]
        if trigger.get("triggerQueries"):
            lines.append("    triggerQueries:")
            for q in trigger["triggerQueries"]:
                lines.append(f"      - {q}")

    lines.append("")
    lines.append("  actions:")

    for action in topic_json.get("actions", []):
        kind = action.get("kind", "")
        if kind == "InvokeFlowAction":
            flow_id = action.get("flowId", "")
            resolved_guid = flow_name_to_guid_map.get(flow_id, guid())
            output_var = "Topic.flowResult"
            if action.get("outputs"):
                first_output = list(action["outputs"].values())[0]
                output_var = f"Topic.{first_output}"

            lines.append(f"    - kind: InvokeFlowAction")
            lines.append(f"      id: invokeFlow_{guid()[:8]}")
            lines.append(f"      output:")
            lines.append(f"        binding:")
            lines.append(f"          output: {output_var}")
            lines.append(f"      flowId: {resolved_guid}")
            lines.append("")

        elif kind == "SendMessage":
            msg = action.get("message", "Done.")
            lines.append(f"    - kind: SendActivity")
            lines.append(f"      id: sendMsg_{guid()[:8]}")
            lines.append(f'      activity: "{msg}"')
            lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Build Power Automate flow JSON from transpiled flow definition
# ---------------------------------------------------------------------------
def build_flow_json(flow_data, flow_guid, conn_ref_names_map, connectors_data):
    """Convert transpiled flow JSON to real Power Automate workflow JSON."""

    # Determine which connectors this flow uses
    connection_references = {}
    for action in flow_data.get("actions", []):
        connector = action.get("connector")
        if connector:
            # Find the key in connectors_data that maps to this connectorId
            for key, conn in connectors_data["connectors"].items():
                if conn["connectorId"] == connector:
                    if connector not in connection_references:
                        connection_references[connector] = {
                            "runtimeSource": "embedded",
                            "connection": {
                                "connectionReferenceLogicalName": conn_ref_names_map[key]
                            },
                            "api": {
                                "name": connector
                            }
                        }
        # Also check nested actions in conditions
        for nested_key in ("ifTrue", "ifFalse"):
            for nested_action in action.get(nested_key, []):
                nested_connector = nested_action.get("connector")
                if nested_connector:
                    for key, conn in connectors_data["connectors"].items():
                        if conn["connectorId"] == nested_connector:
                            if nested_connector not in connection_references:
                                connection_references[nested_connector] = {
                                    "runtimeSource": "embedded",
                                    "connection": {
                                        "connectionReferenceLogicalName": conn_ref_names_map[key]
                                    },
                                    "api": {
                                        "name": nested_connector
                                    }
                                }

    # Build trigger inputs schema from flow trigger
    trigger_schema = {
        "type": "object",
        "properties": {},
        "required": []
    }
    trigger_inputs = flow_data.get("trigger", {}).get("inputs", {})
    if trigger_inputs.get("properties"):
        for prop_name, prop_def in trigger_inputs["properties"].items():
            trigger_schema["properties"][prop_name] = {
                "title": prop_name,
                "type": prop_def.get("type", "string"),
                "x-ms-dynamically-added": True,
                "description": prop_def.get("description", f"Input: {prop_name}"),
                "x-ms-content-hint": "TEXT"
            }
            trigger_schema["required"].append(prop_name)

    if not trigger_schema["required"]:
        del trigger_schema["required"]

    # Build actions
    pa_actions = {}
    prev_action_name = None

    def convert_action(action, idx, prefix=""):
        nonlocal prev_action_name
        kind = action.get("kind", "")
        action_name = f"{prefix}{kind}_{idx}"

        run_after = {}
        if prev_action_name:
            run_after = {prev_action_name: ["Succeeded"]}

        if kind == "ExcelOnline_GetRows":
            pa_action = {
                "runAfter": run_after,
                "metadata": {
                    "operationMetadataId": guid()
                },
                "type": "OpenApiConnection",
                "inputs": {
                    "host": {
                        "connectionName": action["connector"],
                        "operationId": "GetItems",
                        "apiId": f"/providers/Microsoft.PowerApps/apis/{action['connector']}"
                    },
                    "parameters": {
                        "source": action["inputs"].get("source", "OneDrive for Business"),
                        "drive": action["inputs"].get("drive", ""),
                        "file": action["inputs"].get("file", ""),
                        "table": action["inputs"].get("table", "")
                    },
                    "authentication": "@parameters('$authentication')"
                }
            }
            action_name = f"Get_rows_from_Excel_{idx}"
            pa_actions[action_name] = pa_action

        elif kind == "Office365Outlook_SendEmail":
            pa_action = {
                "runAfter": run_after,
                "metadata": {
                    "operationMetadataId": guid()
                },
                "type": "OpenApiConnection",
                "inputs": {
                    "host": {
                        "connectionName": action["connector"],
                        "operationId": "SendEmailV2",
                        "apiId": f"/providers/Microsoft.PowerApps/apis/{action['connector']}"
                    },
                    "parameters": {
                        "emailMessage/To": action["inputs"].get("to", ""),
                        "emailMessage/Subject": action["inputs"].get("subject", ""),
                        "emailMessage/Body": action["inputs"].get("body", ""),
                        "emailMessage/Importance": action["inputs"].get("importance", "Normal")
                    },
                    "authentication": "@parameters('$authentication')"
                }
            }
            action_name = f"Send_an_email_{idx}"
            pa_actions[action_name] = pa_action

        elif kind == "Compose":
            inputs_val = action.get("inputs", "")
            if isinstance(inputs_val, dict):
                inputs_val = inputs_val.get("expression", str(inputs_val))
            pa_action = {
                "runAfter": run_after,
                "metadata": {
                    "operationMetadataId": guid()
                },
                "type": "Compose",
                "inputs": inputs_val
            }
            action_name = f"Compose_{idx}"
            pa_actions[action_name] = pa_action

        elif kind == "Condition":
            # Build if-true and if-false branches
            true_actions = {}
            false_actions = {}
            branch_prev = None
            for i, ta in enumerate(action.get("ifTrue", [])):
                ta_name, ta_def = convert_single_action(ta, i, "True_")
                if branch_prev:
                    ta_def["runAfter"] = {branch_prev: ["Succeeded"]}
                else:
                    ta_def["runAfter"] = {}
                true_actions[ta_name] = ta_def
                branch_prev = ta_name

            branch_prev = None
            for i, fa in enumerate(action.get("ifFalse", [])):
                fa_name, fa_def = convert_single_action(fa, i, "False_")
                if branch_prev:
                    fa_def["runAfter"] = {branch_prev: ["Succeeded"]}
                else:
                    fa_def["runAfter"] = {}
                false_actions[fa_name] = fa_def
                branch_prev = fa_name

            pa_action = {
                "runAfter": run_after,
                "metadata": {
                    "operationMetadataId": guid()
                },
                "type": "If",
                "expression": {
                    "and": [
                        {
                            "greater": [
                                "@length(body('Get_rows_from_Excel_0')?['value'])",
                                0
                            ]
                        }
                    ]
                },
                "actions": true_actions,
                "else": {
                    "actions": false_actions
                }
            }
            action_name = f"Condition_{idx}"
            pa_actions[action_name] = pa_action

        elif kind == "Response":
            response_body = action.get("inputs", {})
            if isinstance(response_body, dict):
                result_val = response_body.get("result", "Done")
            else:
                result_val = str(response_body)

            pa_action = {
                "runAfter": run_after,
                "metadata": {
                    "operationMetadataId": guid()
                },
                "type": "Response",
                "kind": "Skills",
                "inputs": {
                    "statusCode": 200,
                    "body": {
                        "output": result_val
                    },
                    "schema": {
                        "type": "object",
                        "properties": {
                            "output": {
                                "title": "output",
                                "x-ms-dynamically-added": True,
                                "type": "string"
                            }
                        }
                    }
                }
            }
            action_name = f"Respond_to_Copilot_{idx}"
            pa_actions[action_name] = pa_action

        else:
            # Generic action
            pa_action = {
                "runAfter": run_after,
                "type": "Compose",
                "inputs": str(action)
            }
            action_name = f"Action_{idx}"
            pa_actions[action_name] = pa_action

        prev_action_name = action_name
        return action_name

    def convert_single_action(action, idx, prefix=""):
        """Convert a single action and return (name, definition) without adding to pa_actions."""
        kind = action.get("kind", "")
        action_name = f"{prefix}{kind}_{idx}"

        if kind == "Compose":
            inputs_val = action.get("inputs", "")
            if isinstance(inputs_val, dict):
                inputs_val = inputs_val.get("expression", str(inputs_val))
            return (f"{prefix}Compose_{idx}", {
                "runAfter": {},
                "metadata": {"operationMetadataId": guid()},
                "type": "Compose",
                "inputs": inputs_val
            })

        elif kind == "Office365Outlook_SendEmail":
            return (f"{prefix}Send_email_{idx}", {
                "runAfter": {},
                "metadata": {"operationMetadataId": guid()},
                "type": "OpenApiConnection",
                "inputs": {
                    "host": {
                        "connectionName": action["connector"],
                        "operationId": "SendEmailV2",
                        "apiId": f"/providers/Microsoft.PowerApps/apis/{action['connector']}"
                    },
                    "parameters": {
                        "emailMessage/To": action["inputs"].get("to", ""),
                        "emailMessage/Subject": action["inputs"].get("subject", ""),
                        "emailMessage/Body": action["inputs"].get("body", ""),
                        "emailMessage/Importance": action["inputs"].get("importance", "Normal")
                    },
                    "authentication": "@parameters('$authentication')"
                }
            })

        elif kind == "Response":
            response_body = action.get("inputs", {})
            if isinstance(response_body, dict):
                result_val = response_body.get("result", "Done")
            else:
                result_val = str(response_body)
            return (f"{prefix}Respond_{idx}", {
                "runAfter": {},
                "metadata": {"operationMetadataId": guid()},
                "type": "Response",
                "kind": "Skills",
                "inputs": {
                    "statusCode": 200,
                    "body": {"output": result_val},
                    "schema": {
                        "type": "object",
                        "properties": {
                            "output": {
                                "title": "output",
                                "x-ms-dynamically-added": True,
                                "type": "string"
                            }
                        }
                    }
                }
            })

        elif kind == "ExcelOnline_GetRows":
            return (f"{prefix}Get_rows_{idx}", {
                "runAfter": {},
                "metadata": {"operationMetadataId": guid()},
                "type": "OpenApiConnection",
                "inputs": {
                    "host": {
                        "connectionName": action["connector"],
                        "operationId": "GetItems",
                        "apiId": f"/providers/Microsoft.PowerApps/apis/{action['connector']}"
                    },
                    "parameters": {
                        "source": action["inputs"].get("source", "OneDrive for Business"),
                        "drive": action["inputs"].get("drive", ""),
                        "file": action["inputs"].get("file", ""),
                        "table": action["inputs"].get("table", "")
                    },
                    "authentication": "@parameters('$authentication')"
                }
            })

        else:
            return (f"{prefix}Action_{idx}", {
                "runAfter": {},
                "type": "Compose",
                "inputs": str(action)
            })

    # Convert top-level actions
    for idx, action in enumerate(flow_data.get("actions", [])):
        convert_action(action, idx)

    flow_json = {
        "properties": {
            "connectionReferences": connection_references,
            "definition": {
                "$schema": "https://schema.management.azure.com/providers/Microsoft.Logic/schemas/2016-06-01/workflowdefinition.json#",
                "contentVersion": "1.0.0.0",
                "parameters": {
                    "$connections": {
                        "defaultValue": {},
                        "type": "Object"
                    },
                    "$authentication": {
                        "defaultValue": {},
                        "type": "SecureObject"
                    }
                },
                "triggers": {
                    "manual": {
                        "metadata": {
                            "operationMetadataId": guid()
                        },
                        "type": "Request",
                        "kind": "Skills",
                        "inputs": {
                            "schema": trigger_schema
                        }
                    }
                },
                "actions": pa_actions,
                "outputs": {}
            },
            "templateName": ""
        },
        "schemaVersion": "1.0.0.0"
    }

    return flow_json


# ---------------------------------------------------------------------------
# Generate XML helpers
# ---------------------------------------------------------------------------
def address_xml():
    nil_fields = [
        "City", "County", "Country", "Fax", "FreightTermsCode",
        "ImportSequenceNumber", "Latitude", "Line1", "Line2", "Line3",
        "Longitude", "Name", "PostalCode", "PostOfficeBox",
        "PrimaryContactName", "StateOrProvince",
        "Telephone1", "Telephone2", "Telephone3",
        "TimeZoneRuleVersionNumber", "UPSZone", "UTCOffset",
        "UTCConversionTimeZoneCode"
    ]
    addresses = []
    for num in [1, 2]:
        lines = [f"        <Address>"]
        lines.append(f"          <AddressNumber>{num}</AddressNumber>")
        lines.append(f"          <AddressTypeCode>1</AddressTypeCode>")
        for field in nil_fields:
            if field == "ShippingMethodCode":
                continue
            lines.append(f'          <{field} xsi:nil="true"></{field}>')
            if field == "FreightTermsCode":
                pass
            if field == "PostOfficeBox":
                pass
        # Insert ShippingMethodCode after PrimaryContactName
        # Actually let's just put it in the right place
        lines.append(f"          <ShippingMethodCode>1</ShippingMethodCode>")
        lines.append(f"        </Address>")
        addresses.append("\n".join(lines))
    return "\n".join(addresses)


def build_solution_xml(workflow_guids):
    root_components = ""
    for wf_guid in workflow_guids:
        root_components += f'      <RootComponent type="29" id="{braced_guid(wf_guid)}" behavior="0" />\n'

    nil = 'xsi:nil="true"'
    addr_fields = ["City", "County", "Country", "Fax", "FreightTermsCode",
                    "ImportSequenceNumber", "Latitude", "Line1", "Line2", "Line3",
                    "Longitude", "Name", "PostalCode", "PostOfficeBox",
                    "PrimaryContactName", "StateOrProvince",
                    "Telephone1", "Telephone2", "Telephone3",
                    "TimeZoneRuleVersionNumber", "UPSZone", "UTCOffset",
                    "UTCConversionTimeZoneCode"]

    def addr_block(num):
        lines = [f"        <Address>",
                 f"          <AddressNumber>{num}</AddressNumber>",
                 f"          <AddressTypeCode>1</AddressTypeCode>"]
        for f in addr_fields:
            lines.append(f'          <{f} {nil}></{f}>')
        lines.append("          <ShippingMethodCode>1</ShippingMethodCode>")
        lines.append("        </Address>")
        return "\n".join(lines)

    return f"""<ImportExportXml version="9.2.25114.191" SolutionPackageVersion="9.2" languagecode="1033" generatedBy="CrmLive" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <SolutionManifest>
    <UniqueName>{SOLUTION_UNIQUE_NAME}</UniqueName>
    <LocalizedNames>
      <LocalizedName description="{SOLUTION_DISPLAY_NAME}" languagecode="1033" />
    </LocalizedNames>
    <Descriptions />
    <Version>{SOLUTION_VERSION}</Version>
    <Managed>0</Managed>
    <Publisher>
      <UniqueName>{PUBLISHER_UNIQUE_NAME}</UniqueName>
      <LocalizedNames>
        <LocalizedName description="{PUBLISHER_DISPLAY_NAME}" languagecode="1033" />
      </LocalizedNames>
      <Descriptions>
        <Description description="{PUBLISHER_DESCRIPTION}" languagecode="1033" />
      </Descriptions>
      <EMailAddress {nil}></EMailAddress>
      <SupportingWebsiteUrl {nil}></SupportingWebsiteUrl>
      <CustomizationPrefix>{PUBLISHER_PREFIX}</CustomizationPrefix>
      <CustomizationOptionValuePrefix>{PUBLISHER_OPTION_VALUE_PREFIX}</CustomizationOptionValuePrefix>
      <Addresses>
{addr_block(1)}
{addr_block(2)}
      </Addresses>
    </Publisher>
    <RootComponents>
{root_components.rstrip()}
    </RootComponents>
    <MissingDependencies />
  </SolutionManifest>
</ImportExportXml>"""


def build_customizations_xml(workflow_entries, conn_refs):
    workflows_xml = ""
    for entry in workflow_entries:
        desc_xml = ""
        if entry.get("description"):
            desc_xml = f"""
      <Descriptions>
        <Description languagecode="1033" description="{entry['description']}" />
      </Descriptions>"""

        workflows_xml += f"""    <Workflow WorkflowId="{braced_guid(entry['guid'])}" Name="{entry['name']}">
      <JsonFileName>/Workflows/{entry['filename']}</JsonFileName>
      <Type>1</Type>
      <Subprocess>0</Subprocess>
      <Category>5</Category>
      <Mode>0</Mode>
      <Scope>4</Scope>
      <OnDemand>0</OnDemand>
      <TriggerOnCreate>0</TriggerOnCreate>
      <TriggerOnDelete>0</TriggerOnDelete>
      <AsyncAutodelete>0</AsyncAutodelete>
      <SyncWorkflowLogOnFailure>0</SyncWorkflowLogOnFailure>
      <StateCode>1</StateCode>
      <StatusCode>2</StatusCode>
      <RunAs>1</RunAs>
      <IsTransacted>1</IsTransacted>
      <IntroducedVersion>1.0.0.0</IntroducedVersion>
      <IsCustomizable>1</IsCustomizable>
      <IsCustomProcessingStepAllowedForOtherPublishers>1</IsCustomProcessingStepAllowedForOtherPublishers>
      <ModernFlowType>0</ModernFlowType>
      <PrimaryEntity>none</PrimaryEntity>
      <LocalizedNames>
        <LocalizedName languagecode="1033" description="{entry['name']}" />
      </LocalizedNames>{desc_xml}
    </Workflow>
"""

    conn_refs_xml = ""
    for ref in conn_refs:
        conn_refs_xml += f"""    <connectionreference connectionreferencelogicalname="{ref['logicalname']}">
      <connectionreferencedisplayname>{ref['displayname']}</connectionreferencedisplayname>
      <connectorid>/providers/Microsoft.PowerApps/apis/{ref['connectorid']}</connectorid>
      <iscustomizable>1</iscustomizable>
      <promptingbehavior>0</promptingbehavior>
      <statecode>0</statecode>
      <statuscode>1</statuscode>
    </connectionreference>
"""

    return f"""<ImportExportXml xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <Entities></Entities>
  <Roles></Roles>
  <Workflows>
{workflows_xml.rstrip()}
  </Workflows>
  <FieldSecurityProfiles></FieldSecurityProfiles>
  <Templates />
  <EntityMaps />
  <EntityRelationships />
  <OrganizationSettings />
  <optionsets />
  <CustomControls />
  <EntityDataProviders />
  <connectionreferences>
{conn_refs_xml.rstrip()}
  </connectionreferences>
  <Languages>
    <Language>1033</Language>
  </Languages>
</ImportExportXml>"""


def build_bot_xml(schema_name, bot_name):
    return f"""<bot schemaname="{schema_name}">
  <authenticationmode>2</authenticationmode>
  <authenticationtrigger>1</authenticationtrigger>
  <iscustomizable>0</iscustomizable>
  <language>{BOT_LANGUAGE}</language>
  <name>{bot_name}</name>
  <runtimeprovider>0</runtimeprovider>
  <template>{BOT_TEMPLATE}</template>
  <timezoneruleversionnumber>4</timezoneruleversionnumber>
</bot>"""


def build_bot_configuration_json(schema_name):
    return json.dumps({
        "$kind": "BotConfiguration",
        "channels": [
            {"$kind": "ChannelDefinition", "channelId": "MsTeams"}
        ],
        "publishOnImport": True,
        "gPTSettings": {
            "$kind": "GPTSettings",
            "defaultSchemaName": f"{schema_name}.gpt.default"
        },
        "isLightweightBot": False,
        "aISettings": {
            "$kind": "AISettings",
            "useModelKnowledge": True,
            "isSemanticSearchEnabled": True,
            "optInUseLatestModels": False
        },
        "analyticsSettings": {
            "$kind": "AnalyticsSettings"
        }
    }, indent=2)


def build_botcomponent_xml(schema_name, component_type, name, parent_schema,
                           description="", statecode="0", statuscode="1"):
    desc_line = ""
    if description:
        desc_line = f"\n  <description>{description}</description>"
    return f"""<botcomponent schemaname="{schema_name}">
  <componenttype>{component_type}</componenttype>{desc_line}
  <iscustomizable>0</iscustomizable>
  <name>{name}</name>
  <parentbotid>
    <schemaname>{parent_schema}</schemaname>
  </parentbotid>
  <statecode>{statecode}</statecode>
  <statuscode>{statuscode}</statuscode>
</botcomponent>"""


def build_gpt_data(bot_name):
    return f"""kind: GptComponentMetadata
displayName: {bot_name}
instructions:
conversationStarters:
  - title: Read Sales Data
    text: Get today's sales data

  - title: Generate Report
    text: Generate the daily sales report

  - title: Send Report
    text: Send the sales report via email

  - title: Help
    text: What can you do?
"""


def build_content_types_xml(all_parts):
    """Build [Content_Types].xml with overrides for all data files."""
    overrides = ""
    for part in sorted(all_parts):
        overrides += f'<Override PartName="/{part}" ContentType="application/octet-stream" />'

    return (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="xml" ContentType="application/octet-stream" />'
        '<Default Extension="json" ContentType="application/octet-stream" />'
        f'{overrides}'
        '</Types>'
    )


def build_botcomponent_workflowset_xml(topic_flow_mappings):
    """Build Assets/botcomponent_workflowset.xml linking topics to flows."""
    entries = ""
    for mapping in topic_flow_mappings:
        entries += f"""  <botcomponent_workflow botcomponentid.schemaname="{mapping['topic_schema']}" workflowid.workflowid="{mapping['workflow_guid']}">
    <iscustomizable>1</iscustomizable>
  </botcomponent_workflow>
"""
    return f"""<botcomponent_workflowset>
{entries.rstrip()}
</botcomponent_workflowset>"""


# ---------------------------------------------------------------------------
# Assemble the solution zip
# ---------------------------------------------------------------------------
def build_solution():
    files_to_zip = {}  # path_in_zip -> content (str or bytes)
    data_parts = []  # for [Content_Types].xml overrides

    # --- 1. Bot definition ---
    bot_dir = f"bots/{SCHEMA_NAME}"
    files_to_zip[f"{bot_dir}/bot.xml"] = build_bot_xml(SCHEMA_NAME, BOT_NAME)
    files_to_zip[f"{bot_dir}/configuration.json"] = build_bot_configuration_json(SCHEMA_NAME)

    # --- 2. GPT component ---
    gpt_schema = f"{SCHEMA_NAME}.gpt.default"
    gpt_dir = f"botcomponents/{gpt_schema}"
    files_to_zip[f"{gpt_dir}/botcomponent.xml"] = build_botcomponent_xml(
        gpt_schema, 15, BOT_NAME, SCHEMA_NAME, description=BOT_NAME
    )
    files_to_zip[f"{gpt_dir}/data"] = build_gpt_data(BOT_NAME)
    data_parts.append(f"botcomponents/{gpt_schema}/data")

    # --- 3. System topics ---
    for topic_key, topic_def in SYSTEM_TOPICS.items():
        topic_schema = f"{SCHEMA_NAME}.topic.{topic_key}"
        topic_dir = f"botcomponents/{topic_schema}"
        files_to_zip[f"{topic_dir}/botcomponent.xml"] = build_botcomponent_xml(
            topic_schema, 9, topic_def["name"], SCHEMA_NAME,
            description=topic_def["description"],
            statecode=topic_def["statecode"],
            statuscode=topic_def["statuscode"]
        )
        files_to_zip[f"{topic_dir}/data"] = topic_def["data"]
        data_parts.append(f"botcomponents/{topic_schema}/data")

    # --- 4. Custom topics (from transpiled files) ---
    custom_topic_names = {}  # topic_key -> topic_schema
    topic_flow_mappings = []

    for topic_key, topic_json in topics.items():
        # Create a clean topic name for the schema
        display_name = topic_json["displayName"].replace(" ", "")
        topic_schema = f"{SCHEMA_NAME}.topic.{display_name}"
        custom_topic_names[topic_key] = topic_schema
        topic_dir = f"botcomponents/{topic_schema}"

        topic_yaml = build_topic_yaml(topic_json, flow_name_to_guid)

        files_to_zip[f"{topic_dir}/botcomponent.xml"] = build_botcomponent_xml(
            topic_schema, 9, topic_json["displayName"], SCHEMA_NAME,
            statecode="0", statuscode="1"
        )
        files_to_zip[f"{topic_dir}/data"] = topic_yaml
        data_parts.append(f"botcomponents/{topic_schema}/data")

        # Track topic-to-flow mappings for botcomponent_workflowset
        for action in topic_json.get("actions", []):
            if action.get("kind") == "InvokeFlowAction":
                flow_id = action.get("flowId", "")
                if flow_id in flow_name_to_guid:
                    topic_flow_mappings.append({
                        "topic_schema": topic_schema,
                        "workflow_guid": flow_name_to_guid[flow_id]
                    })

    # --- 5. Workflows (Power Automate flows) ---
    workflow_entries = []
    all_workflow_guids = []

    for flow_key, flow_data in flows.items():
        wf_guid = flow_guids[flow_key]
        all_workflow_guids.append(wf_guid)
        display_name = flow_data["displayName"]
        safe_name = display_name.replace(" ", "")
        filename = f"{safe_name}-{upper_guid(wf_guid)}.json"

        flow_json = build_flow_json(flow_data, wf_guid, conn_ref_names, connectors)
        files_to_zip[f"Workflows/{filename}"] = json.dumps(flow_json, indent=2)

        workflow_entries.append({
            "guid": wf_guid,
            "name": display_name,
            "description": flow_data.get("description", ""),
            "filename": filename
        })

    # --- 6. Connection references ---
    conn_refs = []
    for key, conn in connectors["connectors"].items():
        conn_refs.append({
            "logicalname": conn_ref_names[key],
            "displayname": conn["displayName"],
            "connectorid": conn["connectorId"]
        })

    # --- 7. solution.xml ---
    files_to_zip["solution.xml"] = build_solution_xml(all_workflow_guids)

    # --- 8. customizations.xml ---
    files_to_zip["customizations.xml"] = build_customizations_xml(workflow_entries, conn_refs)

    # --- 9. Assets/botcomponent_workflowset.xml ---
    if topic_flow_mappings:
        files_to_zip["Assets/botcomponent_workflowset.xml"] = build_botcomponent_workflowset_xml(
            topic_flow_mappings
        )

    # --- 10. [Content_Types].xml ---
    files_to_zip["[Content_Types].xml"] = build_content_types_xml(data_parts)

    # --- Write the zip ---
    with zipfile.ZipFile(OUTPUT_ZIP, "w", zipfile.ZIP_DEFLATED) as zf:
        for path, content in sorted(files_to_zip.items()):
            if isinstance(content, bytes):
                zf.writestr(path, content)
            else:
                zf.writestr(path, content)

    print(f"Solution built: {OUTPUT_ZIP}")
    print(f"  Schema name: {SCHEMA_NAME}")
    print(f"  Topics: {len(SYSTEM_TOPICS)} system + {len(topics)} custom")
    print(f"  Flows: {len(flows)}")
    print(f"  Connection references: {len(conn_refs)}")
    print(f"  Total files in zip: {len(files_to_zip)}")

    # List zip contents
    with zipfile.ZipFile(OUTPUT_ZIP, "r") as zf:
        print("\nZip contents:")
        for info in zf.infolist():
            print(f"  {info.filename} ({info.file_size} bytes)")


if __name__ == "__main__":
    build_solution()
