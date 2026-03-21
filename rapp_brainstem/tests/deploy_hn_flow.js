/**
 * Creates the Hacker News Power Automate flow via Dataverse API.
 * Reuses the manage-agent token cache for authentication.
 *
 * Usage: node tests/deploy_hn_flow.js
 */

const { execSync } = require("child_process");
const fs = require("fs");
const path = require("path");
const https = require("https");

const connPath = path.join(
  __dirname, "..", "copilot-studio", "RAPP Brainstem", ".mcs", "conn.json"
);
const conn = JSON.parse(fs.readFileSync(connPath, "utf-8"));
const DATAVERSE_URL = conn.DataverseEndpoint.replace(/\/$/, "");

const MANAGE_AGENT = path.join(
  process.env.HOME || process.env.USERPROFILE,
  ".claude", "plugins", "cache", "skills-for-copilot-studio",
  "copilot-studio", "1.0.4", "scripts", "manage-agent.bundle.js"
);

// ── Flow definition ────────────────────────────────────────────────
const FLOW_DEFINITION = {
  properties: {
    definition: {
      "$schema": "https://schema.management.azure.com/providers/Microsoft.Logic/schemas/2016-06-01/workflowdefinition.json#",
      contentVersion: "1.0.0.0",
      triggers: {
        manual: {
          type: "Request",
          kind: "Button",
          inputs: {
            schema: { type: "object", properties: {}, required: [] }
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
            variables: [{
              name: "formattedStories",
              type: "string",
              value: ""
            }]
          }
        },
        Initialize_Counter: {
          runAfter: { Initialize_Result: ["Succeeded"] },
          type: "InitializeVariable",
          inputs: {
            variables: [{
              name: "counter",
              type: "integer",
              value: 0
            }]
          }
        },
        Loop_Through_Stories: {
          runAfter: { Initialize_Counter: ["Succeeded"] },
          type: "Foreach",
          foreach: "@outputs('Take_First_10')",
          actions: {
            Increment_Counter: {
              type: "IncrementVariable",
              inputs: { name: "counter", value: 1 }
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
        Respond_to_Copilot: {
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
    parameters: {},
    schemaVersion: "1.0.0.0"
  }
};

// ── HTTP helper ────────────────────────────────────────────────────
function request(url, method, headers, body) {
  return new Promise((resolve, reject) => {
    const u = new URL(url);
    const req = https.request({
      hostname: u.hostname,
      path: u.pathname + u.search,
      method,
      headers,
    }, (res) => {
      let data = "";
      res.on("data", (c) => (data += c));
      res.on("end", () => resolve({ status: res.statusCode, headers: res.headers, body: data }));
    });
    req.on("error", reject);
    if (body) req.write(body);
    req.end();
  });
}

// ── Get token via manage-agent's internal acquireToken ──────────
async function getDataverseToken() {
  // The manage-agent list-agents command needs a Dataverse token internally.
  // We'll run a small Node script that imports the bundle's token cache.
  // Simpler approach: use PowerShell MSAL or direct ROPC.
  //
  // Actually, the simplest: use the manage-agent.bundle.js internal exports
  // if available, or call the Dataverse token endpoint with the cached refresh token.

  // Use a trick: run manage-agent with a dummy command that outputs the token
  // Actually, let's just use the Dataverse token that manage-agent cached.
  // The token is stored in the OS credential store, but we can't easily access it.

  // Simplest reliable approach: use device code flow via Node MSAL
  const msal = require("@azure/msal-node");

  const app = new msal.PublicClientApplication({
    auth: {
      clientId: "51f81489-12ee-4a9e-aaae-a2591f45987d",
      authority: `https://login.microsoftonline.com/${conn.AccountInfo.TenantId}`,
    }
  });

  // Try silent first (uses MSAL cache)
  const accounts = await app.getTokenCache().getAllAccounts();
  if (accounts.length > 0) {
    try {
      const result = await app.acquireTokenSilent({
        scopes: [`${DATAVERSE_URL}/.default`],
        account: accounts[0],
      });
      return result.accessToken;
    } catch (e) {
      // Fall through to interactive
    }
  }

  // Interactive browser login
  console.error("Opening browser for Dataverse authentication...");
  const result = await app.acquireTokenInteractive({
    scopes: [`${DATAVERSE_URL}/.default`],
    openBrowser: async (url) => {
      const { exec } = require("child_process");
      exec(`start "" "${url}"`);
    },
    successTemplate: "<h1>Authentication complete. You can close this window.</h1>",
  });
  return result.accessToken;
}

// ── Main ───────────────────────────────────────────────────────────
(async () => {
  console.log("Getting Dataverse token...");

  let token;
  try {
    token = await getDataverseToken();
  } catch (e) {
    // MSAL might not be installed - try alternative
    console.error("MSAL not available, trying alternative auth...");
    console.error("Install with: npm install @azure/msal-node");
    console.error("\nOr pass a token directly: node tests/deploy_hn_flow.js <token>");

    if (process.argv[2]) {
      token = process.argv[2];
    } else {
      process.exit(1);
    }
  }

  console.log("Token acquired. Creating flow...");

  const headers = {
    Authorization: `Bearer ${token}`,
    "Content-Type": "application/json; charset=utf-8",
    "OData-MaxVersion": "4.0",
    "OData-Version": "4.0",
    Accept: "application/json",
    Prefer: "return=representation",
  };

  // Try creating with category=5 (modern cloud flow)
  for (const category of [5, 2]) {
    const payload = JSON.stringify({
      name: "Get Hacker News Top Stories",
      category: category,
      type: 1,
      primaryentity: "none",
      clientdata: JSON.stringify(FLOW_DEFINITION),
    });

    console.log(`Trying category=${category}...`);
    const resp = await request(
      `${DATAVERSE_URL}/api/data/v9.2/workflows`,
      "POST", headers, payload
    );

    if (resp.status === 201 || resp.status === 204) {
      // Get the workflow ID from the Location header
      const location = resp.headers["odata-entityid"] || resp.headers.location || "";
      const idMatch = location.match(/workflows\(([^)]+)\)/);
      const flowId = idMatch ? idMatch[1] : "unknown";

      console.log(`\nFlow created successfully!`);
      console.log(`  Workflow ID: ${flowId}`);
      console.log(`  Category: ${category}`);
      console.log(JSON.stringify({ status: "ok", flowId, category }, null, 2));

      // Now enable the flow
      console.log("\nEnabling flow...");
      const enableResp = await request(
        `${DATAVERSE_URL}/api/data/v9.2/workflows(${flowId})`,
        "PATCH", headers,
        JSON.stringify({ statecode: 1, statuscode: 2 })
      );
      console.log(`Enable status: ${enableResp.status}`);

      // Update the topic YAML with the real flow ID
      const topicPath = path.join(
        __dirname, "..", "copilot-studio", "RAPP Brainstem", "topics",
        "cr720_rappBrainstem.topic.HackerNews.mcs.yml"
      );
      if (fs.existsSync(topicPath)) {
        let yaml = fs.readFileSync(topicPath, "utf-8");
        yaml = yaml.replace(
          /flowId: .*/,
          `flowId: ${flowId}`
        );
        fs.writeFileSync(topicPath, yaml, "utf-8");
        console.log(`\nUpdated topic YAML with flowId: ${flowId}`);
      }

      return;
    }

    console.log(`  Status ${resp.status}: ${resp.body.substring(0, 300)}`);
  }

  console.error("\nFailed to create flow with any category.");
  process.exit(1);
})();
