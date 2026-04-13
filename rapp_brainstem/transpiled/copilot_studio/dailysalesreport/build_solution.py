#!/usr/bin/env python3
"""
Build a Power Platform solution .zip from transpiled Copilot Studio agent files.

Architecture (simplified):
  - ONE Power Automate flow that recreates the agent.py logic natively
    (Excel read → condition → format → send email → respond)
  - Copilot Studio agent with instructions that route to the flow
  - One main topic that invokes the flow and shows the result

Reads:
  - agent_manifest.json, connectors.json
  - flows/flow_generate_report.json (the end-to-end flow)

Produces:
  - DailySalesReport_1_0_0_0.zip (importable via `pac solution import`)
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
SOLUTION_VERSION = "1.0.0.1"

PUBLISHER_UNIQUE_NAME = "RAPPPublisher"
PUBLISHER_DISPLAY_NAME = "RAPP Publisher"
PUBLISHER_PREFIX = "rapp"
PUBLISHER_OPTION_VALUE_PREFIX = "10000"

BOT_NAME = "Daily Sales Report"
BOT_LANGUAGE = 1033
BOT_TEMPLATE = "default-2.1.0"


def short_suffix(length=6):
    return "".join(random.choice(string.ascii_letters + string.digits) for _ in range(length))


def guid():
    return str(uuid.uuid4()).lower()


def braced(g):
    return "{" + g + "}"


# ---------------------------------------------------------------------------
# Read transpiled files
# ---------------------------------------------------------------------------
def load_json(path):
    with open(path, "r") as f:
        return json.load(f)


manifest = load_json(SCRIPT_DIR / "agent_manifest.json")
connectors_data = load_json(SCRIPT_DIR / "connectors.json")
flow_source = load_json(SCRIPT_DIR / "flows" / "flow_generate_report.json")

# ---------------------------------------------------------------------------
# Identifiers (stable across rebuilds by using fixed seed from solution name)
# ---------------------------------------------------------------------------
SCHEMA_NAME = f"{PUBLISHER_PREFIX}_dailysalesreport_{short_suffix()}"
FLOW_GUID = guid()
FLOW_NAME = flow_source.get("displayName", "Generate and Send Daily Report")
FLOW_FILENAME = f"{FLOW_NAME.replace(' ', '')}-{FLOW_GUID.upper()}.json"

# Connection reference logical names
EXCEL_CONN_REF = f"{PUBLISHER_PREFIX}_shared_excelonlinebusiness_{short_suffix(5)}"
OUTLOOK_CONN_REF = f"{PUBLISHER_PREFIX}_shared_office365_{short_suffix(5)}"

# ---------------------------------------------------------------------------
# Build the single Power Automate flow JSON
# ---------------------------------------------------------------------------
def build_flow_json():
    """
    Recreates the agent.py logic as a native Power Automate flow:
    1. Trigger from Copilot (Skills)
    2. Get rows from Excel table (SalesData)
    3. Condition: any rows?
       True:  Compose HTML report → Send email → Respond success
       False: Send "no data" email → Respond no data
    """
    return {
        "properties": {
            "connectionReferences": {
                "shared_excelonlinebusiness": {
                    "runtimeSource": "invoker",
                    "connection": {
                        "connectionReferenceLogicalName": EXCEL_CONN_REF
                    },
                    "api": {"name": "shared_excelonlinebusiness"}
                },
                "shared_office365": {
                    "runtimeSource": "invoker",
                    "connection": {
                        "connectionReferenceLogicalName": OUTLOOK_CONN_REF
                    },
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
                "triggers": {
                    "manual": {
                        "metadata": {"operationMetadataId": guid()},
                        "type": "Request",
                        "kind": "PowerVirtualAgents",
                        "inputs": {
                            "schema": {
                                "type": "object",
                                "properties": {},
                                "required": []
                            }
                        }
                    }
                },
                "actions": {
                    "Get_rows": {
                        "runAfter": {},
                        "metadata": {"operationMetadataId": guid()},
                        "type": "OpenApiConnection",
                        "inputs": {
                            "host": {
                                "connectionName": "shared_excelonlinebusiness",
                                "operationId": "GetItems",
                                "apiId": "/providers/Microsoft.PowerApps/apis/shared_excelonlinebusiness"
                            },
                            "parameters": {
                                "source": "OneDrive for Business",
                                "drive": "",
                                "file": "",
                                "table": "SalesData"
                            },
                            "authentication": "@parameters('$authentication')"
                        }
                    },
                    "Check_data": {
                        "runAfter": {"Get_rows": ["Succeeded"]},
                        "metadata": {"operationMetadataId": guid()},
                        "type": "If",
                        "expression": {
                            "and": [{
                                "greater": [
                                    "@length(body('Get_rows')?['value'])",
                                    0
                                ]
                            }]
                        },
                        "actions": {
                            "Format_report": {
                                "runAfter": {},
                                "metadata": {"operationMetadataId": guid()},
                                "type": "Compose",
                                "inputs": "@concat('<h2>Daily Sales Report</h2><p>Total rows: ', string(length(body('Get_rows')?['value'])), '</p>')"
                            },
                            "Send_report_email": {
                                "runAfter": {"Format_report": ["Succeeded"]},
                                "metadata": {"operationMetadataId": guid()},
                                "type": "OpenApiConnection",
                                "inputs": {
                                    "host": {
                                        "connectionName": "shared_office365",
                                        "operationId": "SendEmailV2",
                                        "apiId": "/providers/Microsoft.PowerApps/apis/shared_office365"
                                    },
                                    "parameters": {
                                        "emailMessage/To": "",
                                        "emailMessage/Subject": "Daily Sales Report - @{utcNow('yyyy-MM-dd')}",
                                        "emailMessage/Body": "@outputs('Format_report')",
                                        "emailMessage/Importance": "Normal"
                                    },
                                    "authentication": "@parameters('$authentication')"
                                }
                            },
                            "Respond_success": {
                                "runAfter": {"Send_report_email": ["Succeeded"]},
                                "metadata": {"operationMetadataId": guid()},
                                "type": "Response",
                                "kind": "PowerVirtualAgents",
                                "inputs": {
                                    "statusCode": 200,
                                    "body": {
                                        "output": "Report generated and sent successfully. Found @{length(body('Get_rows')?['value'])} rows of sales data."
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
                        },
                        "else": {
                            "actions": {
                                "Send_no_data_email": {
                                    "runAfter": {},
                                    "metadata": {"operationMetadataId": guid()},
                                    "type": "OpenApiConnection",
                                    "inputs": {
                                        "host": {
                                            "connectionName": "shared_office365",
                                            "operationId": "SendEmailV2",
                                            "apiId": "/providers/Microsoft.PowerApps/apis/shared_office365"
                                        },
                                        "parameters": {
                                            "emailMessage/To": "",
                                            "emailMessage/Subject": "Daily Sales Report - No Data - @{utcNow('yyyy-MM-dd')}",
                                            "emailMessage/Body": "<p>No sales data available for today.</p>",
                                            "emailMessage/Importance": "Low"
                                        },
                                        "authentication": "@parameters('$authentication')"
                                    }
                                },
                                "Respond_no_data": {
                                    "runAfter": {"Send_no_data_email": ["Succeeded"]},
                                    "metadata": {"operationMetadataId": guid()},
                                    "type": "Response",
                                    "kind": "PowerVirtualAgents",
                                    "inputs": {
                                        "statusCode": 200,
                                        "body": {
                                            "output": "No sales data found for today. A notification email has been sent."
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
                            }
                        }
                    }
                },
                "outputs": {}
            },
            "templateName": ""
        },
        "schemaVersion": "1.0.0.0"
    }


# ---------------------------------------------------------------------------
# Build solution.xml
# ---------------------------------------------------------------------------
def build_solution_xml():
    nil = 'xsi:nil="true"'
    addr_fields = "\n".join(
        f"          <{f} {nil}></{f}>"
        for f in [
            "City", "County", "Country", "Fax", "FreightTermsCode",
            "ImportSequenceNumber", "Latitude", "Line1", "Line2", "Line3",
            "Longitude", "Name", "PostalCode", "PostOfficeBox",
            "PrimaryContactName", "StateOrProvince",
            "Telephone1", "Telephone2", "Telephone3",
            "TimeZoneRuleVersionNumber", "UPSZone", "UTCOffset",
            "UTCConversionTimeZoneCode"
        ]
    )
    addr_block = lambda n: f"""        <Address>
          <AddressNumber>{n}</AddressNumber>
          <AddressTypeCode>1</AddressTypeCode>
{addr_fields}
          <ShippingMethodCode>1</ShippingMethodCode>
        </Address>"""

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
        <Description description="{PUBLISHER_DISPLAY_NAME}" languagecode="1033" />
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
      <RootComponent type="29" id="{braced(FLOW_GUID)}" behavior="0" />
    </RootComponents>
    <MissingDependencies />
  </SolutionManifest>
</ImportExportXml>"""


# ---------------------------------------------------------------------------
# Build customizations.xml
# ---------------------------------------------------------------------------
def build_customizations_xml():
    return f"""<ImportExportXml xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <Entities></Entities>
  <Roles></Roles>
  <Workflows>
    <Workflow WorkflowId="{braced(FLOW_GUID)}" Name="{FLOW_NAME}" Description="Reads Excel sales data, formats report, sends via Outlook">
      <JsonFileName>/Workflows/{FLOW_FILENAME}</JsonFileName>
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
        <LocalizedName languagecode="1033" description="{FLOW_NAME}" />
      </LocalizedNames>
      <Descriptions>
        <Description languagecode="1033" description="Reads Excel sales data, formats report, sends via Outlook" />
      </Descriptions>
    </Workflow>
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
    <connectionreference connectionreferencelogicalname="{EXCEL_CONN_REF}">
      <connectionreferencedisplayname>Excel Online (Business)</connectionreferencedisplayname>
      <connectorid>/providers/Microsoft.PowerApps/apis/shared_excelonlinebusiness</connectorid>
      <iscustomizable>1</iscustomizable>
      <promptingbehavior>0</promptingbehavior>
      <statecode>0</statecode>
      <statuscode>1</statuscode>
    </connectionreference>
    <connectionreference connectionreferencelogicalname="{OUTLOOK_CONN_REF}">
      <connectionreferencedisplayname>Office 365 Outlook</connectionreferencedisplayname>
      <connectorid>/providers/Microsoft.PowerApps/apis/shared_office365</connectorid>
      <iscustomizable>1</iscustomizable>
      <promptingbehavior>0</promptingbehavior>
      <statecode>0</statecode>
      <statuscode>1</statuscode>
    </connectionreference>
  </connectionreferences>
  <Languages>
    <Language>1033</Language>
  </Languages>
</ImportExportXml>"""


# ---------------------------------------------------------------------------
# Bot XML and configuration
# ---------------------------------------------------------------------------
def build_bot_xml():
    return f"""<bot schemaname="{SCHEMA_NAME}">
  <authenticationmode>2</authenticationmode>
  <authenticationtrigger>1</authenticationtrigger>
  <iscustomizable>0</iscustomizable>
  <language>{BOT_LANGUAGE}</language>
  <name>{BOT_NAME}</name>
  <runtimeprovider>0</runtimeprovider>
  <template>{BOT_TEMPLATE}</template>
  <timezoneruleversionnumber>4</timezoneruleversionnumber>
</bot>"""


def build_bot_config():
    return json.dumps({
        "$kind": "BotConfiguration",
        "channels": [
            {"$kind": "ChannelDefinition", "channelId": "MsTeams"}
        ],
        "publishOnImport": True,
        "gPTSettings": {
            "$kind": "GPTSettings",
            "defaultSchemaName": f"{SCHEMA_NAME}.gpt.default"
        },
        "isLightweightBot": False,
        "aISettings": {
            "$kind": "AISettings",
            "useModelKnowledge": True,
            "isSemanticSearchEnabled": True,
            "optInUseLatestModels": False
        },
        "analyticsSettings": {"$kind": "AnalyticsSettings"}
    }, indent=2)


# ---------------------------------------------------------------------------
# GPT component (instructions live here)
# ---------------------------------------------------------------------------
AGENT_INSTRUCTIONS = """You are the Daily Sales Report assistant. You help users generate and send daily sales reports from Excel data.

When a user asks you to generate a report, run the daily sales report, get sales data, or send a report — invoke the "Generate and Send Daily Report" flow. This flow will:
1. Read sales data from the SalesData Excel table
2. Check if any data exists
3. If data exists: format an HTML report and email it
4. If no data: send a notification email instead
5. Return the result to you

Always tell the user what happened after the flow completes. If the flow reports success, confirm the report was sent. If no data was found, let the user know."""


def build_gpt_data():
    return f"""kind: GptComponentMetadata
displayName: {BOT_NAME}
instructions: |
{chr(10).join('  ' + line if line else '' for line in AGENT_INSTRUCTIONS.split(chr(10)))}
conversationStarters:
  - title: Generate Report
    text: Generate the daily sales report

  - title: Check Sales Data
    text: Do we have sales data for today?

  - title: Send Report
    text: Send the sales report via email

  - title: Help
    text: What can you do?
"""


def build_gpt_botcomponent_xml():
    return f"""<botcomponent schemaname="{SCHEMA_NAME}.gpt.default">
  <componenttype>12</componenttype>
  <iscustomizable>0</iscustomizable>
  <name>default</name>
  <parentbotid>
    <schemaname>{SCHEMA_NAME}</schemaname>
  </parentbotid>
  <statecode>1</statecode>
  <statuscode>2</statuscode>
</botcomponent>"""


# ---------------------------------------------------------------------------
# Main topic — invokes the flow and shows result
# ---------------------------------------------------------------------------
def build_main_topic_data():
    return f"""kind: AdaptiveDialog
modelDescription: This topic handles all daily sales report requests. Trigger this when a user asks to generate, send, or check sales reports.
beginDialog:
  kind: OnRecognizedIntent
  id: main
  intent:
    displayName: Daily Sales Report
    includeInOnSelectIntent: true
    triggerQueries:
      - generate daily report
      - run the daily sales report
      - send the sales report
      - get sales data
      - daily sales summary
      - check today's numbers
      - create and send report
      - email the report

  actions:
    - kind: SendActivity
      id: sendActivity_start
      activity: "Running the daily sales report flow..."

    - kind: InvokeFlowAction
      id: invokeFlow_report
      output:
        binding:
          output: Topic.ReportResult
      flowId: {FLOW_GUID}

    - kind: SendActivity
      id: sendActivity_result
      activity: "${{Topic.ReportResult}}"
"""


def build_main_topic_botcomponent_xml():
    return f"""<botcomponent schemaname="{SCHEMA_NAME}.topic.DailySalesReport">
  <componenttype>9</componenttype>
  <iscustomizable>0</iscustomizable>
  <name>Daily Sales Report</name>
  <parentbotid>
    <schemaname>{SCHEMA_NAME}</schemaname>
  </parentbotid>
  <statecode>1</statecode>
  <statuscode>2</statuscode>
</botcomponent>"""


# ---------------------------------------------------------------------------
# System topics (minimal required set)
# ---------------------------------------------------------------------------
SYSTEM_TOPICS = {
    "ConversationStart": {
        "componenttype": 9, "statecode": 1, "statuscode": 2,
        "data": """kind: AdaptiveDialog
beginDialog:
  kind: OnConversationStart
  id: main
  actions:
    - kind: SendActivity
      id: sendActivity_greeting
      activity: "Hi! I'm your Daily Sales Report assistant. I can generate and send your daily sales report from Excel. Just ask me to run the report!"
"""
    },
    "Escalate": {
        "componenttype": 9, "statecode": 1, "statuscode": 2,
        "data": """kind: AdaptiveDialog
beginDialog:
  kind: OnRecognizedIntent
  id: main
  intent:
    displayName: Escalate
    triggerQueries:
      - talk to agent
      - talk to a real person
  actions:
    - kind: SendActivity
      id: sendActivity_esc
      activity: "I'll connect you with someone who can help."
    - kind: TransferToAgent
      id: transfer_agent
"""
    },
    "Fallback": {
        "componenttype": 9, "statecode": 1, "statuscode": 2,
        "data": """kind: AdaptiveDialog
beginDialog:
  kind: OnUnknownIntent
  id: main
  actions:
    - kind: SendActivity
      id: sendActivity_fallback
      activity: "I'm not sure I understand. I can help you generate and send daily sales reports. Try asking me to 'generate the daily report'."
"""
    },
    "Greeting": {
        "componenttype": 9, "statecode": 1, "statuscode": 2,
        "data": """kind: AdaptiveDialog
beginDialog:
  kind: OnRecognizedIntent
  id: main
  intent:
    displayName: Greeting
    triggerQueries:
      - hello
      - hi
      - hey
      - good morning
      - good afternoon
  actions:
    - kind: SendActivity
      id: sendActivity_greet
      activity: "Hello! Ready to generate your daily sales report? Just say the word."
"""
    },
    "Goodbye": {
        "componenttype": 9, "statecode": 1, "statuscode": 2,
        "data": """kind: AdaptiveDialog
beginDialog:
  kind: OnRecognizedIntent
  id: main
  intent:
    displayName: Goodbye
    triggerQueries:
      - bye
      - goodbye
      - see you later
  actions:
    - kind: SendActivity
      id: sendActivity_bye
      activity: "Goodbye! Have a great day."
    - kind: EndConversation
      id: endConversation
"""
    },
    "ThankYou": {
        "componenttype": 9, "statecode": 1, "statuscode": 2,
        "data": """kind: AdaptiveDialog
beginDialog:
  kind: OnRecognizedIntent
  id: main
  intent:
    displayName: ThankYou
    triggerQueries:
      - thank you
      - thanks
  actions:
    - kind: SendActivity
      id: sendActivity_thanks
      activity: "You're welcome!"
"""
    },
    "OnError": {
        "componenttype": 9, "statecode": 1, "statuscode": 2,
        "data": """kind: AdaptiveDialog
beginDialog:
  kind: OnError
  id: main
  actions:
    - kind: SendActivity
      id: sendActivity_error
      activity: "Something went wrong. Please try again."
"""
    },
}


# ---------------------------------------------------------------------------
# Workflowset (links topic to flow)
# ---------------------------------------------------------------------------
def build_workflowset_xml():
    return f"""<botcomponent_workflowset>
  <botcomponent_workflow botcomponentid.schemaname="{SCHEMA_NAME}.topic.DailySalesReport" workflowid.workflowid="{FLOW_GUID}">
    <iscustomizable>1</iscustomizable>
  </botcomponent_workflow>
</botcomponent_workflowset>"""


# ---------------------------------------------------------------------------
# Content Types
# ---------------------------------------------------------------------------
def build_content_types(data_parts):
    overrides = "".join(
        f'<Override PartName="/{p}" ContentType="application/octet-stream" />'
        for p in sorted(data_parts)
    )
    return (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="xml" ContentType="application/octet-stream" />'
        '<Default Extension="json" ContentType="application/octet-stream" />'
        f'{overrides}'
        '</Types>'
    )


# ---------------------------------------------------------------------------
# Package it all
# ---------------------------------------------------------------------------
def build():
    files = {}
    data_parts = []

    bot_dir = f"bots/{SCHEMA_NAME}"
    comp_dir = f"botcomponents/{SCHEMA_NAME}"

    # Solution structure
    files["solution.xml"] = build_solution_xml()
    files["customizations.xml"] = build_customizations_xml()

    # Bot
    files[f"{bot_dir}/bot.xml"] = build_bot_xml()
    files[f"{bot_dir}/configuration.json"] = build_bot_config()

    # GPT component (instructions)
    gpt_dir = f"{comp_dir}.gpt.default"
    files[f"{gpt_dir}/data"] = build_gpt_data()
    files[f"{gpt_dir}/botcomponent.xml"] = build_gpt_botcomponent_xml()
    data_parts.append(f"{gpt_dir}/data")

    # Main topic
    topic_dir = f"{comp_dir}.topic.DailySalesReport"
    files[f"{topic_dir}/data"] = build_main_topic_data()
    files[f"{topic_dir}/botcomponent.xml"] = build_main_topic_botcomponent_xml()
    data_parts.append(f"{topic_dir}/data")

    # System topics
    for topic_name, topic_info in SYSTEM_TOPICS.items():
        t_dir = f"{comp_dir}.topic.{topic_name}"
        files[f"{t_dir}/data"] = topic_info["data"]
        files[f"{t_dir}/botcomponent.xml"] = f"""<botcomponent schemaname="{SCHEMA_NAME}.topic.{topic_name}">
  <componenttype>{topic_info['componenttype']}</componenttype>
  <iscustomizable>0</iscustomizable>
  <name>{topic_name}</name>
  <parentbotid>
    <schemaname>{SCHEMA_NAME}</schemaname>
  </parentbotid>
  <statecode>{topic_info['statecode']}</statecode>
  <statuscode>{topic_info['statuscode']}</statuscode>
</botcomponent>"""
        data_parts.append(f"{t_dir}/data")

    # Power Automate flow
    files[f"Workflows/{FLOW_FILENAME}"] = json.dumps(build_flow_json(), indent=2)

    # Workflowset
    files["Assets/botcomponent_workflowset.xml"] = build_workflowset_xml()

    # Content types
    files["[Content_Types].xml"] = build_content_types(data_parts)

    # Write zip
    with zipfile.ZipFile(OUTPUT_ZIP, "w", zipfile.ZIP_DEFLATED) as zf:
        for path, content in sorted(files.items()):
            zf.writestr(path, content)

    print(f"Built: {OUTPUT_ZIP}")
    print(f"  Schema: {SCHEMA_NAME}")
    print(f"  Flow GUID: {FLOW_GUID}")
    print(f"  Files: {len(files)}")
    print(f"  Version: {SOLUTION_VERSION}")


if __name__ == "__main__":
    build()
