/**
 * Creates the Hacker News Power Automate cloud flow via Dataverse Web API.
 * Uses the same auth tokens as manage-agent (cached in OS credential store).
 *
 * Usage: node tests/create_hn_flow.js
 */

const fs = require("fs");
const path = require("path");
const https = require("https");

const connPath = path.join(
  __dirname, "..", "copilot-studio", "RAPP Brainstem", ".mcs", "conn.json"
);
const conn = JSON.parse(fs.readFileSync(connPath, "utf-8"));
const DATAVERSE_URL = conn.DataverseEndpoint.replace(/\/$/, "");

// Flow definition: Copilot trigger → HTTP calls → format → respond
const FLOW_DEFINITION = {
  properties: {
    definition: {
      "$schema": "https://schema.management.azure.com/providers/Microsoft.Logic/schemas/2016-06-01/workflowdefinition.json#",
      contentVersion: "1.0.0.0",
      triggers: {
        When_an_agent_calls_this_flow: {
          type: "Request",
          kind: "Button",
          inputs: {
            schema: {
              type: "object",
              properties: {},
              required: []
            }
          }
        }
      },
      actions: {
        Get_Top_Story_IDs: {
          runAfter: {},
          type: "Http",
          inputs: {
            method: "GET",
            uri: "https://hacker-news.firebaseio.com/v0/topstories.json"
          }
        },
        Take_First_10: {
          runAfter: { Get_Top_Story_IDs: ["Succeeded"] },
          type: "Compose",
          inputs: "@take(body('Get_Top_Story_IDs'), 10)"
        },
        Initialize_Result: {
          runAfter: { Take_First_10: ["Succeeded"] },
          type: "InitializeVariable",
          inputs: {
            variables: [
              {
                name: "formattedStories",
                type: "string",
                value: ""
              }
            ]
          }
        },
        Initialize_Counter: {
          runAfter: { Initialize_Result: ["Succeeded"] },
          type: "InitializeVariable",
          inputs: {
            variables: [
              {
                name: "counter",
                type: "integer",
                value: 0
              }
            ]
          }
        },
        Loop_Through_Stories: {
          runAfter: { Initialize_Counter: ["Succeeded"] },
          type: "Foreach",
          foreach: "@outputs('Take_First_10')",
          actions: {
            Increment_Counter: {
              type: "IncrementVariable",
              inputs: {
                name: "counter",
                value: 1
              }
            },
            Get_Story_Details: {
              runAfter: { Increment_Counter: ["Succeeded"] },
              type: "Http",
              inputs: {
                method: "GET",
                uri: "https://hacker-news.firebaseio.com/v0/item/@{items('Loop_Through_Stories')}.json"
              }
            },
            Append_to_Result: {
              runAfter: { Get_Story_Details: ["Succeeded"] },
              type: "AppendToStringVariable",
              inputs: {
                name: "formattedStories",
                value: "@{variables('counter')}. @{body('Get_Story_Details')?['title']} — @{body('Get_Story_Details')?['url']} (Score: @{body('Get_Story_Details')?['score']}, by @{body('Get_Story_Details')?['by']})\n"
              }
            }
          },
          operationOptions: "Sequential"
        },
        Respond_to_agent: {
          runAfter: { Loop_Through_Stories: ["Succeeded"] },
          type: "Response",
          kind: "Http",
          inputs: {
            statusCode: 200,
            body: {
              formattedStories: "@variables('formattedStories')"
            },
            schema: {
              type: "object",
              properties: {
                formattedStories: { type: "string", title: "formattedStories" }
              }
            }
          }
        }
      }
    },
    connectionReferences: {},
    parameters: {}
  }
};

async function getDataverseToken() {
  // Use manage-agent to get a fresh Dataverse token
  const { execSync } = require("child_process");
  const manageAgent = path.join(
    process.env.HOME || process.env.USERPROFILE,
    ".claude", "plugins", "cache", "skills-for-copilot-studio",
    "copilot-studio", "1.0.4", "scripts", "manage-agent.bundle.js"
  );

  // The manage-agent auth command acquires tokens - let's use its token cache
  // We need the Dataverse token specifically
  try {
    const result = execSync(
      `node "${manageAgent}" auth --tenant-id "${conn.AccountInfo.TenantId}" --environment-url "${DATAVERSE_URL}" --environment-id "${conn.EnvironmentId}" --agent-mgmt-url "${conn.AgentManagementEndpoint}"`,
      { timeout: 60000, encoding: "utf-8" }
    );
    const parsed = JSON.parse(result.trim());
    if (parsed.status === "ok" && parsed.dataverseToken) {
      return parsed.dataverseToken;
    }
  } catch (e) {
    // Auth might output to stderr, token to stdout
  }

  // Fallback: use the list-agents command which requires a Dataverse token
  // and capture it from the debug output
  throw new Error(
    "Could not acquire Dataverse token automatically.\n" +
    "Run this manually:\n" +
    `  node "${manageAgent}" auth --tenant-id "${conn.AccountInfo.TenantId}"` +
    ` --environment-url "${DATAVERSE_URL}"` +
    ` --environment-id "${conn.EnvironmentId}"` +
    ` --agent-mgmt-url "${conn.AgentManagementEndpoint}"\n` +
    "Then pass the token: node tests/create_hn_flow.js <dataverse-token>"
  );
}

function httpsRequest(url, options, body) {
  return new Promise((resolve, reject) => {
    const urlObj = new URL(url);
    const opts = {
      hostname: urlObj.hostname,
      path: urlObj.pathname + urlObj.search,
      ...options,
    };
    const req = https.request(opts, (res) => {
      let data = "";
      res.on("data", (chunk) => (data += chunk));
      res.on("end", () => {
        resolve({ status: res.statusCode, headers: res.headers, body: data });
      });
    });
    req.on("error", reject);
    if (body) req.write(body);
    req.end();
  });
}

async function createFlow(token) {
  const payload = {
    name: "Get Hacker News Top Stories",
    category: 5, // Desktop flow=6, Cloud flow=5 in some environments, 2 in others
    type: 1, // Definition type
    primaryentity: "none",
    clientdata: JSON.stringify(FLOW_DEFINITION),
    statecode: 0, // Draft
    statuscode: 1, // Draft
  };

  console.log("Creating flow via Dataverse API...");

  const response = await httpsRequest(
    `${DATAVERSE_URL}/api/data/v9.2/workflows`,
    {
      method: "POST",
      headers: {
        Authorization: `Bearer ${token}`,
        "Content-Type": "application/json; charset=utf-8",
        "OData-MaxVersion": "4.0",
        "OData-Version": "4.0",
        Accept: "application/json",
        Prefer: "return=representation",
      },
    },
    JSON.stringify(payload)
  );

  console.log(`Response status: ${response.status}`);

  if (response.status === 201 || response.status === 200) {
    const result = JSON.parse(response.body);
    console.log(`Flow created! ID: ${result.workflowid}`);
    console.log(`Name: ${result.name}`);
    return result;
  } else {
    console.error("Failed to create flow:");
    console.error(response.body);

    // Try with category=2 if category=5 failed
    if (payload.category === 5) {
      console.log("\nRetrying with category=2...");
      payload.category = 2;
      const retry = await httpsRequest(
        `${DATAVERSE_URL}/api/data/v9.2/workflows`,
        {
          method: "POST",
          headers: {
            Authorization: `Bearer ${token}`,
            "Content-Type": "application/json; charset=utf-8",
            "OData-MaxVersion": "4.0",
            "OData-Version": "4.0",
            Accept: "application/json",
            Prefer: "return=representation",
          },
        },
        JSON.stringify(payload)
      );

      console.log(`Retry status: ${retry.status}`);
      if (retry.status === 201 || retry.status === 200) {
        const result = JSON.parse(retry.body);
        console.log(`Flow created! ID: ${result.workflowid}`);
        return result;
      }
      console.error(retry.body);
    }

    return null;
  }
}

(async () => {
  let token = process.argv[2];

  if (!token) {
    try {
      token = await getDataverseToken();
    } catch (e) {
      console.error(e.message);
      console.log("\nAlternative: pass a Dataverse access token as an argument:");
      console.log("  node tests/create_hn_flow.js <your-dataverse-token>");
      process.exit(1);
    }
  }

  const result = await createFlow(token);
  if (result) {
    console.log(JSON.stringify({ status: "ok", flowId: result.workflowid, name: result.name }, null, 2));
  } else {
    process.exit(1);
  }
})();
