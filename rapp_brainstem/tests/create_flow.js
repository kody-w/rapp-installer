/**
 * Creates the Hacker News Power Automate flow via Dataverse API.
 * Uses device code flow for auth (no PowerShell needed).
 *
 * Usage: node tests/create_flow.js
 */

const fs = require("fs");
const path = require("path");
const https = require("https");
const http = require("http");
const querystring = require("querystring");

const connPath = path.join(__dirname, "..", "copilot-studio", "RAPP Brainstem", ".mcs", "conn.json");
const conn = JSON.parse(fs.readFileSync(connPath, "utf-8"));
const DATAVERSE_URL = conn.DataverseEndpoint.replace(/\/$/, "");
const TENANT_ID = conn.AccountInfo.TenantId;
const CLIENT_ID = "51f81489-12ee-4a9e-aaae-a2591f45987d";

// ── Flow definition ────────────────────────────────────────────────
const FLOW_DEF = {
  properties: {
    definition: {
      "$schema": "https://schema.management.azure.com/providers/Microsoft.Logic/schemas/2016-06-01/workflowdefinition.json#",
      contentVersion: "1.0.0.0",
      triggers: {
        manual: { type: "Request", kind: "Button", inputs: { schema: { type: "object", properties: {}, required: [] } } }
      },
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

// ── HTTPS helpers ──────────────────────────────────────────────────
function post(hostname, path, headers, body) {
  return new Promise((resolve, reject) => {
    const req = https.request({ hostname, path, method: "POST", headers }, (res) => {
      let d = ""; res.on("data", c => d += c);
      res.on("end", () => resolve({ status: res.statusCode, headers: res.headers, body: d }));
    });
    req.on("error", reject);
    req.write(body);
    req.end();
  });
}

function req(url, method, headers, body) {
  return new Promise((resolve, reject) => {
    const u = new URL(url);
    const r = https.request({ hostname: u.hostname, path: u.pathname + u.search, method, headers }, (res) => {
      let d = ""; res.on("data", c => d += c);
      res.on("end", () => resolve({ status: res.statusCode, headers: res.headers, body: d }));
    });
    r.on("error", reject);
    if (body) r.write(body);
    r.end();
  });
}

function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

// ── Device code flow ───────────────────────────────────────────────
async function getToken() {
  console.log("Starting device code authentication...\n");

  const deviceResp = await post(
    "login.microsoftonline.com",
    `/${TENANT_ID}/oauth2/v2.0/devicecode`,
    { "Content-Type": "application/x-www-form-urlencoded" },
    querystring.stringify({
      client_id: CLIENT_ID,
      scope: `${DATAVERSE_URL}/.default offline_access`,
    })
  );

  const device = JSON.parse(deviceResp.body);
  console.log("╔══════════════════════════════════════════════╗");
  console.log(`║  Open: ${device.verification_uri}`);
  console.log(`║  Code: ${device.user_code}`);
  console.log("╚══════════════════════════════════════════════╝\n");
  console.log("Waiting for sign-in...");

  // Poll for token
  for (let i = 0; i < 120; i++) {
    await sleep(device.interval * 1000 || 5000);

    const tokenResp = await post(
      "login.microsoftonline.com",
      `/${TENANT_ID}/oauth2/v2.0/token`,
      { "Content-Type": "application/x-www-form-urlencoded" },
      querystring.stringify({
        client_id: CLIENT_ID,
        grant_type: "urn:ietf:params:oauth:grant-type:device_code",
        device_code: device.device_code,
      })
    );

    const result = JSON.parse(tokenResp.body);
    if (result.access_token) {
      console.log("Authenticated!\n");
      return result.access_token;
    }
    if (result.error && result.error !== "authorization_pending") {
      throw new Error(`Auth error: ${result.error_description || result.error}`);
    }
    process.stderr.write(".");
  }

  throw new Error("Auth timed out.");
}

// ── Create flow ────────────────────────────────────────────────────
async function createFlow(token) {
  const headers = {
    Authorization: `Bearer ${token}`,
    "Content-Type": "application/json; charset=utf-8",
    "OData-MaxVersion": "4.0", "OData-Version": "4.0",
    Accept: "application/json",
    Prefer: "return=representation",
  };

  console.log("Creating flow via Dataverse API...");
  const resp = await req(`${DATAVERSE_URL}/api/data/v9.2/workflows`, "POST", headers,
    JSON.stringify({
      name: "Get Hacker News Top Stories",
      category: 5,
      type: 1,
      primaryentity: "none",
      clientdata: JSON.stringify(FLOW_DEF),
    })
  );

  if (resp.status === 201 || resp.status === 204) {
    const loc = resp.headers["odata-entityid"] || "";
    const m = loc.match(/workflows\(([^)]+)\)/);
    const flowId = m ? m[1] : JSON.parse(resp.body).workflowid;
    console.log(`Flow created! ID: ${flowId}`);

    // Enable
    console.log("Enabling flow...");
    const enable = await req(`${DATAVERSE_URL}/api/data/v9.2/workflows(${flowId})`, "PATCH", headers,
      JSON.stringify({ statecode: 1, statuscode: 2 }));
    console.log(`Enable: ${enable.status}`);

    return flowId;
  }

  console.error(`Failed (${resp.status}): ${resp.body.substring(0, 500)}`);
  return null;
}

// ── Main ───────────────────────────────────────────────────────────
(async () => {
  try {
    const token = process.argv[2] || await getToken();
    const flowId = await createFlow(token);
    if (flowId) {
      console.log(`\n✓ Flow ID: ${flowId}`);
      console.log(`  Update HackerNews topic flowId to: ${flowId}`);
      console.log(JSON.stringify({ status: "ok", flowId }));
    }
  } catch (e) {
    console.error(e.message);
    process.exit(1);
  }
})();
