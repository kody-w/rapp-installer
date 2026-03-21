/**
 * Creates the HN Power Automate flow using curl for HTTP calls
 * (works around Node.js DNS/proxy issues on this machine).
 */
const { execSync } = require("child_process");
const fs = require("fs");
const path = require("path");

const connPath = path.join(__dirname, "..", "copilot-studio", "RAPP Brainstem", ".mcs", "conn.json");
const conn = JSON.parse(fs.readFileSync(connPath, "utf-8"));
const DATAVERSE_URL = conn.DataverseEndpoint.replace(/\/$/, "");
const TENANT_ID = conn.AccountInfo.TenantId;
const CLIENT_ID = "51f81489-12ee-4a9e-aaae-a2591f45987d";

const FLOW_DEF = {
  properties: {
    definition: {
      "$schema": "https://schema.management.azure.com/providers/Microsoft.Logic/schemas/2016-06-01/workflowdefinition.json#",
      contentVersion: "1.0.0.0",
      triggers: { manual: { type: "Request", kind: "Button", inputs: { schema: { type: "object", properties: {}, required: [] } } } },
      actions: {
        Get_Top_Story_IDs: { runAfter: {}, type: "Http", inputs: { method: "GET", uri: "https://hacker-news.firebaseio.com/v0/topstories.json" } },
        Take_First_10: { runAfter: { Get_Top_Story_IDs: ["Succeeded"] }, type: "Compose", inputs: "@take(body('Get_Top_Story_IDs'), 10)" },
        Initialize_Result: { runAfter: { Take_First_10: ["Succeeded"] }, type: "InitializeVariable", inputs: { variables: [{ name: "formattedStories", type: "string", value: "" }] } },
        Initialize_Counter: { runAfter: { Initialize_Result: ["Succeeded"] }, type: "InitializeVariable", inputs: { variables: [{ name: "counter", type: "integer", value: 0 }] } },
        Loop_Through_Stories: {
          runAfter: { Initialize_Counter: ["Succeeded"] }, type: "Foreach", foreach: "@outputs('Take_First_10')",
          actions: {
            Increment_Counter: { type: "IncrementVariable", inputs: { name: "counter", value: 1 } },
            Get_Story_Details: { runAfter: { Increment_Counter: ["Succeeded"] }, type: "Http", inputs: { method: "GET", uri: "https://hacker-news.firebaseio.com/v0/item/@{items('Loop_Through_Stories')}.json" } },
            Append_to_Result: { runAfter: { Get_Story_Details: ["Succeeded"] }, type: "AppendToStringVariable", inputs: { name: "formattedStories", value: "@{variables('counter')}. @{body('Get_Story_Details')?['title']} — @{body('Get_Story_Details')?['url']} (Score: @{body('Get_Story_Details')?['score']}, by @{body('Get_Story_Details')?['by']})\n" } }
          },
          operationOptions: "Sequential"
        },
        Respond_to_Copilot: { runAfter: { Loop_Through_Stories: ["Succeeded"] }, type: "Response", kind: "Http", inputs: { statusCode: 200, body: { formattedStories: "@variables('formattedStories')" }, schema: { type: "object", properties: { formattedStories: { type: "string", title: "formattedStories" } } } } }
      }
    },
    connectionReferences: {},
    parameters: {},
    schemaVersion: "1.0.0.0"
  }
};

function curlPost(url, headers, body) {
  const headerArgs = Object.entries(headers).map(([k, v]) => `-H "${k}: ${v}"`).join(" ");
  const bodyFile = path.join(__dirname, ".tmp_body.json");
  fs.writeFileSync(bodyFile, body, "utf-8");
  try {
    const result = execSync(
      `curl -s -w "\\n%{http_code}" -X POST ${headerArgs} -d @"${bodyFile}" "${url}"`,
      { encoding: "utf-8", timeout: 30000, maxBuffer: 10 * 1024 * 1024 }
    );
    const lines = result.trim().split("\n");
    const statusCode = parseInt(lines.pop());
    const responseBody = lines.join("\n");
    return { status: statusCode, body: responseBody };
  } finally {
    try { fs.unlinkSync(bodyFile); } catch {}
  }
}

function curlPatch(url, headers, body) {
  const headerArgs = Object.entries(headers).map(([k, v]) => `-H "${k}: ${v}"`).join(" ");
  const result = execSync(
    `curl -s -w "\\n%{http_code}" -X PATCH ${headerArgs} -d '${body}' "${url}"`,
    { encoding: "utf-8", timeout: 30000 }
  );
  const lines = result.trim().split("\n");
  const statusCode = parseInt(lines.pop());
  return { status: statusCode, body: lines.join("\n") };
}

function curlGet(url, headers) {
  const headerArgs = Object.entries(headers).map(([k, v]) => `-H "${k}: ${v}"`).join(" ");
  const result = execSync(
    `curl -s -D - "${url}" ${headerArgs}`,
    { encoding: "utf-8", timeout: 30000 }
  );
  return result;
}

// ── Device code flow via curl ──────────────────────────────────────
function deviceCodeStart() {
  const result = curlPost(
    `https://login.microsoftonline.com/${TENANT_ID}/oauth2/v2.0/devicecode`,
    { "Content-Type": "application/x-www-form-urlencoded" },
    `client_id=${CLIENT_ID}&scope=${encodeURIComponent(DATAVERSE_URL + "/.default offline_access")}`
  );
  return JSON.parse(result.body);
}

function deviceCodePoll(deviceCode) {
  const body = `client_id=${CLIENT_ID}&grant_type=urn%3Aietf%3Aparams%3Aoauth%3Agrant-type%3Adevice_code&device_code=${deviceCode}`;
  const result = curlPost(
    `https://login.microsoftonline.com/${TENANT_ID}/oauth2/v2.0/token`,
    { "Content-Type": "application/x-www-form-urlencoded" },
    body
  );
  return JSON.parse(result.body);
}

function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

(async () => {
  console.log("Starting device code authentication...\n");
  const device = deviceCodeStart();

  console.log("╔══════════════════════════════════════════════════╗");
  console.log(`║  Open:  https://microsoft.com/devicelogin        ║`);
  console.log(`║  Code:  ${device.user_code.padEnd(40)}║`);
  console.log("╚══════════════════════════════════════════════════╝\n");

  // Poll for token (15 min timeout)
  for (let i = 0; i < 180; i++) {
    await sleep((device.interval || 5) * 1000);
    const result = deviceCodePoll(device.device_code);

    if (result.access_token) {
      console.log("Authenticated!\n");

      // Create flow
      const headers = {
        Authorization: `Bearer ${result.access_token}`,
        "Content-Type": "application/json; charset=utf-8",
        "OData-MaxVersion": "4.0",
        "OData-Version": "4.0",
        Accept: "application/json",
      };

      console.log("Creating Power Automate flow...");
      const createResp = curlPost(
        `${DATAVERSE_URL}/api/data/v9.2/workflows`,
        headers,
        JSON.stringify({
          name: "Get Hacker News Top Stories",
          category: 5,
          type: 1,
          primaryentity: "none",
          clientdata: JSON.stringify(FLOW_DEF),
        })
      );

      console.log(`Create status: ${createResp.status}`);
      if (createResp.status === 201 || createResp.status === 204 || createResp.status === 200) {
        let flowId = "unknown";
        try {
          const parsed = JSON.parse(createResp.body);
          flowId = parsed.workflowid || "check-portal";
        } catch {}

        console.log(`Flow created! ID: ${flowId}`);
        console.log(JSON.stringify({ status: "ok", flowId }));
        return;
      }

      console.error(`Failed: ${createResp.body.substring(0, 500)}`);
      process.exit(1);
    }

    if (result.error && result.error !== "authorization_pending") {
      console.error(`Auth error: ${result.error_description}`);
      process.exit(1);
    }
    process.stderr.write(".");
  }

  console.error("\nAuth timed out.");
  process.exit(1);
})();
