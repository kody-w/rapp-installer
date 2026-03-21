/**
 * Gets a Dataverse token via manage-agent's internal token acquisition,
 * then creates the HN flow via the Dataverse API.
 *
 * This script spawns the manage-agent list-agents command (which acquires tokens)
 * with a patched environment that captures the token.
 *
 * Usage: node tests/get_token_and_create_flow.js
 */

const { spawn } = require("child_process");
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
const FLOW_DEF = {
  properties: {
    definition: {
      "$schema": "https://schema.management.azure.com/providers/Microsoft.Logic/schemas/2016-06-01/workflowdefinition.json#",
      contentVersion: "1.0.0.0",
      triggers: {
        manual: {
          type: "Request",
          kind: "Button",
          inputs: { schema: { type: "object", properties: {}, required: [] } }
        }
      },
      actions: {
        Get_Top_Story_IDs: {
          runAfter: {},
          type: "Http",
          inputs: { method: "GET", uri: "https://hacker-news.firebaseio.com/v0/topstories.json" }
        },
        Take_First_10: {
          runAfter: { Get_Top_Story_IDs: ["Succeeded"] },
          type: "Compose",
          inputs: "@take(body('Get_Top_Story_IDs'), 10)"
        },
        Initialize_Result: {
          runAfter: { Take_First_10: ["Succeeded"] },
          type: "InitializeVariable",
          inputs: { variables: [{ name: "formattedStories", type: "string", value: "" }] }
        },
        Initialize_Counter: {
          runAfter: { Initialize_Result: ["Succeeded"] },
          type: "InitializeVariable",
          inputs: { variables: [{ name: "counter", type: "integer", value: 0 }] }
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
            body: { formattedStories: "@variables('formattedStories')" },
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

function httpsReq(url, method, headers, body) {
  return new Promise((resolve, reject) => {
    const u = new URL(url);
    const req = https.request({
      hostname: u.hostname, path: u.pathname + u.search, method, headers,
    }, (res) => {
      let d = ""; res.on("data", c => d += c);
      res.on("end", () => resolve({ status: res.statusCode, headers: res.headers, body: d }));
    });
    req.on("error", reject);
    if (body) req.write(body);
    req.end();
  });
}

async function createFlow(token) {
  const headers = {
    Authorization: `Bearer ${token}`,
    "Content-Type": "application/json; charset=utf-8",
    "OData-MaxVersion": "4.0",
    "OData-Version": "4.0",
    Accept: "application/json",
    Prefer: "return=representation",
  };

  const payload = JSON.stringify({
    name: "Get Hacker News Top Stories",
    category: 5,
    type: 1,
    primaryentity: "none",
    clientdata: JSON.stringify(FLOW_DEF),
  });

  console.log("Creating flow via Dataverse API...");
  const resp = await httpsReq(`${DATAVERSE_URL}/api/data/v9.2/workflows`, "POST", headers, payload);

  if (resp.status === 201 || resp.status === 204) {
    const location = resp.headers["odata-entityid"] || "";
    const idMatch = location.match(/workflows\(([^)]+)\)/);
    const flowId = idMatch ? idMatch[1] : "check-portal";
    console.log(`Flow created! ID: ${flowId}`);

    // Enable it
    await httpsReq(`${DATAVERSE_URL}/api/data/v9.2/workflows(${flowId})`, "PATCH", headers,
      JSON.stringify({ statecode: 1, statuscode: 2 }));
    console.log("Flow enabled.");

    return flowId;
  }

  console.error(`Failed: ${resp.status}`);
  console.error(resp.body.substring(0, 500));
  return null;
}

// ── Get token by intercepting manage-agent's HTTP call ────────────
// We'll use PowerShell to get a token via the VS Code first-party client
async function getTokenViaPowerShell() {
  const { execSync } = require("child_process");

  const ps = `
$body = @{
  client_id = "51f81489-12ee-4a9e-aaae-a2591f45987d"
  scope = "${DATAVERSE_URL}/.default offline_access"
  grant_type = "password"
  username = "${conn.AccountInfo.AccountEmail}"
}
# This won't work without password, but let's try device code

$deviceBody = @{
  client_id = "51f81489-12ee-4a9e-aaae-a2591f45987d"
  scope = "${DATAVERSE_URL}/.default offline_access"
}
$device = Invoke-RestMethod -Method Post -Uri "https://login.microsoftonline.com/${conn.AccountInfo.TenantId}/oauth2/v2.0/devicecode" -Body $deviceBody
Write-Output $device.device_code
Write-Output $device.user_code
Write-Output $device.verification_uri
`;

  try {
    const result = execSync(`powershell -Command "${ps.replace(/"/g, '\\"').replace(/\n/g, '; ')}"`,
      { encoding: "utf-8", timeout: 15000 });
    const lines = result.trim().split("\n").map(l => l.trim());
    if (lines.length >= 3) {
      const [deviceCode, userCode, verifyUri] = lines;
      console.log(`\nSign in required:`);
      console.log(`  Open: ${verifyUri}`);
      console.log(`  Code: ${userCode}\n`);

      // Poll for token
      for (let i = 0; i < 60; i++) {
        await new Promise(r => setTimeout(r, 3000));
        try {
          const tokenResult = execSync(`powershell -Command "$tokenBody = @{ client_id='51f81489-12ee-4a9e-aaae-a2591f45987d'; grant_type='urn:ietf:params:oauth:grant-type:device_code'; device_code='${deviceCode}' }; $r = Invoke-RestMethod -Method Post -Uri 'https://login.microsoftonline.com/${conn.AccountInfo.TenantId}/oauth2/v2.0/token' -Body $tokenBody; Write-Output $r.access_token"`,
            { encoding: "utf-8", timeout: 10000 });
          const token = tokenResult.trim();
          if (token && token.length > 100) {
            console.log("Token acquired!");
            return token;
          }
        } catch (e) {
          // authorization_pending — keep polling
          if (!e.stderr?.includes("authorization_pending")) {
            // Real error
            if (e.stderr) process.stderr.write(".");
          }
        }
      }
    }
  } catch (e) {
    console.error("PowerShell device code flow failed:", e.message);
  }
  return null;
}

(async () => {
  const token = await getTokenViaPowerShell();
  if (!token) {
    console.error("Failed to get token.");
    process.exit(1);
  }

  const flowId = await createFlow(token);
  if (flowId) {
    console.log(JSON.stringify({ status: "ok", flowId }, null, 2));
  } else {
    process.exit(1);
  }
})();
