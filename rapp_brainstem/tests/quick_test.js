/**
 * Quick single-utterance test for RAPP Brainstem in Copilot Studio.
 *
 * Usage:
 *   node tests/quick_test.js "Hi there!"
 *   node tests/quick_test.js "Show me Hacker News" --headed
 *
 * Outputs JSON with the agent's response and a screenshot.
 */

const { chromium } = require("playwright");
const fs = require("fs");
const path = require("path");

const utterance = process.argv[2] || "Hi there!";
const headed = process.argv.includes("--headed");

const connPath = path.join(
  __dirname,
  "..",
  "copilot-studio",
  "RAPP Brainstem",
  ".mcs",
  "conn.json"
);
const conn = JSON.parse(fs.readFileSync(connPath, "utf-8"));
const authPath = path.join(__dirname, ".auth", "state.json");
const hasAuth = fs.existsSync(authPath);

const ENV_ID = conn.EnvironmentId;
const AGENT_ID = conn.AgentId;
// Use overview page — it loads faster and the Test panel works from there
const URL = `https://copilotstudio.microsoft.com/environments/${ENV_ID}/bots/${AGENT_ID}/overview`;

(async () => {
  const browser = await chromium.launch({ headless: !headed && hasAuth });
  const context = hasAuth
    ? await browser.newContext({ storageState: authPath })
    : await browser.newContext();
  const page = await context.newPage();
  page.setDefaultTimeout(60000);

  // Navigate
  await page.goto(URL, { waitUntil: "domcontentloaded", timeout: 30000 });
  await page.waitForTimeout(3000);

  // Handle auth
  const currentUrl = page.url();
  if (
    currentUrl.includes("login.microsoftonline.com") ||
    currentUrl.includes("login.live.com") ||
    !currentUrl.includes("copilotstudio.microsoft.com")
  ) {
    console.error("AUTH REQUIRED — sign in in the browser window...");
    await page.waitForURL("**/copilotstudio.microsoft.com/**", {
      timeout: 180000,
      waitUntil: "domcontentloaded",
    });
    const authDir = path.dirname(authPath);
    if (!fs.existsSync(authDir)) fs.mkdirSync(authDir, { recursive: true });
    await context.storageState({ path: authPath });
    console.error("Auth saved.");
  }

  await page.waitForLoadState("networkidle");
  await page.waitForTimeout(3000);

  // Dismiss any modal dialogs blocking interaction
  const diagDir = path.join(__dirname, "test-results");
  if (!fs.existsSync(diagDir)) fs.mkdirSync(diagDir, { recursive: true });

  const backdrop = page.locator(".fui-DialogSurface__backdrop").first();
  if ((await backdrop.count()) > 0 && (await backdrop.isVisible())) {
    console.error("Dialog backdrop detected — capturing diagnostics...");

    // Screenshot the modal state
    await page.screenshot({ path: path.join(diagDir, "modal-state.png"), fullPage: true });

    // Dump the dialog HTML
    const dialogSurface = page.locator(".fui-DialogSurface").first();
    if ((await dialogSurface.count()) > 0) {
      const dialogHtml = await dialogSurface.evaluate((el) => el.outerHTML);
      fs.writeFileSync(path.join(diagDir, "modal-dialog.html"), dialogHtml, "utf-8");
      console.error("Dialog HTML saved to tests/test-results/modal-dialog.html");

      // Try to find and click any button in the dialog surface
      const dialogButtons = dialogSurface.locator("button");
      const btnCount = await dialogButtons.count();
      console.error(`Found ${btnCount} buttons in dialog`);
      for (let i = 0; i < btnCount; i++) {
        const btnText = await dialogButtons.nth(i).textContent();
        console.error(`  Dialog button[${i}]: "${btnText?.trim()}"`);
      }

      // Prefer "Skip" > "Got it" > "Close" > "OK" > last button
      const preferOrder = ["skip", "got it", "close", "dismiss", "ok", "done"];
      let clicked = false;
      for (const pref of preferOrder) {
        for (let i = 0; i < btnCount; i++) {
          const btnText = (await dialogButtons.nth(i).textContent())?.trim().toLowerCase() || "";
          if (btnText === pref || btnText.startsWith(pref)) {
            console.error(`Clicking dialog button: "${btnText}"`);
            await dialogButtons.nth(i).click({ force: true });
            await page.waitForTimeout(2000);
            clicked = true;
            break;
          }
        }
        if (clicked) break;
      }
      // Fallback: click last button
      if (!clicked && btnCount > 0) {
        const lastText = (await dialogButtons.nth(btnCount - 1).textContent())?.trim();
        console.error(`Fallback: clicking last button: "${lastText}"`);
        await dialogButtons.nth(btnCount - 1).click({ force: true });
        await page.waitForTimeout(2000);
      }
    } else {
      // No dialog surface — try Escape
      console.error("No dialog surface found, pressing Escape...");
      await page.keyboard.press("Escape");
      await page.waitForTimeout(2000);
    }
  }

  // Check if the test chat panel is already open (textarea visible)
  await page.waitForTimeout(2000);

  const input = page
    .locator('textarea[placeholder*="Ask a question"]')
    .or(page.locator('textarea[placeholder*="Type"]'))
    .or(page.locator("textarea.text-area-input"))
    .first();

  const panelAlreadyOpen = (await input.count()) > 0 && (await input.isVisible().catch(() => false));

  if (!panelAlreadyOpen) {
    // Only click Test if the panel is not already open
    console.error("Test panel not open — clicking Test button...");
    const testBtn = page.locator('button[data-telemetry-id="test-chat-button"]')
      .or(page.locator('button:has-text("Test")'))
      .first();

    if ((await testBtn.count()) > 0) {
      await testBtn.click({ force: true, timeout: 15000 });
      await page.waitForTimeout(5000);
    }
  } else {
    console.error("Test panel already open.");
  }

  // Wait for the chat input to become visible
  try {
    await input.waitFor({ state: "visible", timeout: 15000 });
  } catch {
    // Dump page state for debugging
    await page.screenshot({ path: path.join(diagDir, "input-not-visible.png"), fullPage: true });
    const bodyHtml = await page.locator("body").evaluate((el) => el.innerHTML);
    fs.writeFileSync(path.join(diagDir, "page-dump.html"), bodyHtml, "utf-8");
    console.error("Chat input not visible — screenshots and HTML saved for debugging");
    console.log(JSON.stringify({ status: "error", message: "Chat input not visible after opening test panel", debug: path.join(diagDir, "input-not-visible.png") }));
    await browser.close();
    process.exit(1);
  }

  // Count existing bot messages before sending
  const messagesBefore = await page.locator('[class*="webchat__bubble--from-bot"]').count();

  // Type and send
  await input.fill(utterance);
  await page.waitForTimeout(500);

  const sendBtn = page
    .locator('button[aria-label*="Send"]')
    .or(page.locator('button[title*="Send"]'))
    .first();
  if ((await sendBtn.count()) > 0) {
    await sendBtn.click();
  } else {
    await input.press("Enter");
  }

  console.error(`Sent: "${utterance}"`);

  // Wait for response — watch for new content in the chat area
  // The agent typically responds within 5-15 seconds
  await page.waitForTimeout(12000);

  // Capture the chat content — the test chat uses webchat__basic-transcript
  let responseText = "";

  const chatTranscript = page.locator('[class*="basic-transcript"]')
    .or(page.locator('[role="log"]'))
    .or(page.locator('[class*="webchat__basic-transcript"]'))
    .first();

  // Try multiple strategies to find bot messages
  const botSelectors = [
    '[class*="webchat__bubble--from-bot"]',
    '[class*="from-bot"]',
    '[class*="bubble--from-bot"]',
    '[data-testid*="bot"]',
  ];

  for (const sel of botSelectors) {
    const botMessages = page.locator(sel);
    const botMsgCount = await botMessages.count();
    if (botMsgCount > 0) {
      const lastBot = botMessages.nth(botMsgCount - 1);
      responseText = (await lastBot.textContent()) || "";
      console.error(`Found ${botMsgCount} bot messages via "${sel}", last: "${responseText.slice(0, 200)}"`);
      break;
    }
  }

  // Fallback: get all transcript text
  if (!responseText && (await chatTranscript.count()) > 0) {
    responseText = (await chatTranscript.textContent()) || "";
    console.error(`Fallback: transcript text: "${responseText.slice(0, 200)}"`);
  }

  // Last fallback: grab the entire test panel right-side content
  if (!responseText) {
    const rightPanel = page.locator('[class*="test-chat"]')
      .or(page.locator('[class*="TestChat"]'))
      .or(page.locator('[class*="rightPanel"]'))
      .or(page.locator('[class*="side-panel"]'))
      .first();
    if ((await rightPanel.count()) > 0) {
      responseText = (await rightPanel.textContent()) || "";
      console.error(`Panel text: "${responseText.slice(0, 300)}"`);
    }
  }

  // Screenshot + HTML dump
  const ssDir = path.join(__dirname, "test-results");
  if (!fs.existsSync(ssDir)) fs.mkdirSync(ssDir, { recursive: true });
  const ssPath = path.join(ssDir, "quick-test.png");
  await page.screenshot({ path: ssPath });

  // Dump the full page HTML for debugging (truncated to relevant parts)
  const htmlPath = path.join(ssDir, "quick-test-chat.html");
  const fullHtml = await page.content();
  fs.writeFileSync(htmlPath, fullHtml, "utf-8");

  console.log(
    JSON.stringify({
      status: "ok",
      utterance: utterance,
      response: responseText.trim().slice(-800),
      screenshot: ssPath,
      html_dump: htmlPath,
    })
  );

  await browser.close();
})().catch(async (err) => {
  // On failure, try to capture diagnostics
  console.log(JSON.stringify({ status: "error", message: err.message }));
  process.exit(1);
});
