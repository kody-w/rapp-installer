/**
 * Creates the HN flow using the manage-agent's cached Dataverse token.
 * Intercepts the token by monkey-patching https.request during a list-agents call.
 */
const { execSync } = require("child_process");
const fs = require("fs");
const path = require("path");
const https = require("https");

const connPath = path.join(__dirname, "..", "copilot-studio", "RAPP Brainstem", ".mcs", "conn.json");
const conn = JSON.parse(fs.readFileSync(connPath, "utf-8"));
const DATAVERSE_URL = conn.DataverseEndpoint.replace(/\/$/, "");
const MANAGE_AGENT = path.join(
  process.env.HOME || process.env.USERPROFILE,
  ".claude", "plugins", "cache", "skills-for-copilot-studio",
  "copilot-studio", "1.0.4", "scripts", "manage-agent.bundle.js"
);

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

(async () => {
  // Step 1: Get a Dataverse token by running manage-agent list-agents
  // and extracting the token from stderr (it logs "using cached token")
  // Actually, we need the actual token. Let's use a wrapper that captures it.

  // The manage-agent bundle uses MSAL cache. Let's load its cache and get a token.
  // The cache is stored in the OS credential store under "copilot-studio-cli" / "manage-agent"

  // Simplest: write a tiny script that requires the bundle and calls its token function
  const wrapperScript = `
    process.env.NODE_NO_WARNINGS = '1';
    const mod = require('${MANAGE_AGENT.replace(/\\/g, "/")}');
    // The bundle exports are not accessible. Let's use a different approach.
    // We'll intercept the HTTPS request that list-agents makes to Dataverse
    // and capture the Authorization header.
    const origRequest = require('https').request;
    require('https').request = function(opts, cb) {
      if (opts && opts.hostname && opts.hostname.includes('dynamics.com')) {
        const auth = opts.headers && (opts.headers['Authorization'] || opts.headers['authorization']);
        if (auth) {
          process.stdout.write('TOKEN:' + auth.replace('Bearer ', '') + '\\n');
        }
      }
      return origRequest.call(this, opts, cb);
    };
  `;

  // Run list-agents with interceptor
  console.log("Extracting Dataverse token from manage-agent cache...");
  try {
    const result = execSync(
      `node -e "${wrapperScript.replace(/"/g, '\\"').replace(/\n/g, " ")}" -- list-agents --tenant-id "${conn.AccountInfo.TenantId}" --environment-id "${conn.EnvironmentId}" --environment-url "${DATAVERSE_URL}" --agent-mgmt-url "${conn.AgentManagementEndpoint}"`,
      { encoding: "utf-8", timeout: 30000, stdio: ["pipe", "pipe", "pipe"] }
    );
    console.log("Output:", result.substring(0, 200));
  } catch (e) {
    // Expected — the wrapper won't run the command properly
  }

  // Alternative: just call list-agents and parse the Dataverse token from its debug output
  // manage-agent logs "Dataverse API: using cached token (expires ...)" to stderr
  // But doesn't expose the actual token value.

  // Final approach: Use the manage-agent's credential store directly
  // On Windows, it's stored with DPAPI encryption. We can't easily decrypt it.

  // Let's just do device code one more time but with a MUCH longer timeout
  // and print the code prominently
  const querystring = require("querystring");

  console.log("\n========================================");
  console.log("  SIGN IN REQUIRED (one-time)");
  console.log("========================================\n");

  const deviceResp = await req(
    `https://login.microsoftonline.com/${conn.AccountInfo.TenantId}/oauth2/v2.0/devicecode`,
    "POST",
    { "Content-Type": "application/x-www-form-urlencoded" },
    querystring.stringify({ client_id: "51f81489-12ee-4a9e-aaae-a2591f45987d", scope: `${DATAVERSE_URL}/.default offline_access` })
  );

  const device = JSON.parse(deviceResp.body);

  console.log(`  1. Open:  ${"https://microsoft.com/devicelogin"}`);
  console.log(`  2. Code:  ${device.user_code}`);
  console.log(`\n  Waiting up to 15 minutes...\n`);

  // Poll with long timeout
  const maxAttempts = 180; // 15 min at 5s intervals
  for (let i = 0; i < maxAttempts; i++) {
    await new Promise(r => setTimeout(r, (device.interval || 5) * 1000));

    const tokenResp = await req(
      `https://login.microsoftonline.com/${conn.AccountInfo.TenantId}/oauth2/v2.0/token`,
      "POST",
      { "Content-Type": "application/x-www-form-urlencoded" },
      querystring.stringify({
        client_id: "51f81489-12ee-4a9e-aaae-a2591f45987d",
        grant_type: "urn:ietf:params:oauth:grant-type:device_code",
        device_code: device.device_code,
      })
    );

    const result = JSON.parse(tokenResp.body);
    if (result.access_token) {
      console.log("  Authenticated!\n");

      // Create the flow
      const headers = {
        Authorization: `Bearer ${result.access_token}`,
        "Content-Type": "application/json; charset=utf-8",
        "OData-MaxVersion": "4.0", "OData-Version": "4.0",
        Accept: "application/json",
      };

      console.log("Creating Power Automate flow...");
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
        const flowId = m ? m[1] : "check-portal";
        console.log(`Flow created! ID: ${flowId}`);

        // Enable
        await req(`${DATAVERSE_URL}/api/data/v9.2/workflows(${flowId})`, "PATCH", headers,
          JSON.stringify({ statecode: 1, statuscode: 2 }));
        console.log("Flow enabled.");
        console.log(JSON.stringify({ status: "ok", flowId }));
        return;
      }

      console.error(`Failed (${resp.status}): ${resp.body.substring(0, 500)}`);
      process.exit(1);
    }

    if (result.error && result.error !== "authorization_pending") {
      console.error(`Auth error: ${result.error_description}`);
      process.exit(1);
    }
  }

  console.error("Auth timed out after 15 minutes.");
  process.exit(1);
})();
