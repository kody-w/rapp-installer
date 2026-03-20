/**
 * Runs all test cases against the RAPP Brainstem agent in Copilot Studio.
 * Opens one browser session, sends each utterance, validates responses.
 *
 * Usage: node tests/run_all_tests.js [--headed]
 */

const { chromium } = require("playwright");
const fs = require("fs");
const path = require("path");

const headed = process.argv.includes("--headed");
const testCases = JSON.parse(
  fs.readFileSync(path.join(__dirname, "test_cases.json"), "utf-8")
);

const connPath = path.join(
  __dirname, "..", "copilot-studio", "RAPP Brainstem", ".mcs", "conn.json"
);
const conn = JSON.parse(fs.readFileSync(connPath, "utf-8"));
const authPath = path.join(__dirname, ".auth", "state.json");
const hasAuth = fs.existsSync(authPath);
const diagDir = path.join(__dirname, "test-results");

const URL = `https://copilotstudio.microsoft.com/environments/${conn.EnvironmentId}/bots/${conn.AgentId}/overview`;

async function dismissDialogs(page) {
  // Dismiss ALL visible dialogs — onboarding, feedback, telemetry, etc.
  for (let attempt = 0; attempt < 5; attempt++) {
    const backdrop = page.locator(".fui-DialogSurface__backdrop").first();
    if ((await backdrop.count()) === 0 || !(await backdrop.isVisible().catch(() => false))) {
      break; // No more dialogs
    }

    const dialogSurface = page.locator(".fui-DialogSurface").first();
    if ((await dialogSurface.count()) > 0) {
      const buttons = dialogSurface.locator("button");
      const btnCount = await buttons.count();

      // Try dismiss buttons in priority order
      const dismissWords = ["skip", "no, don't", "no don't", "no,", "close", "dismiss", "got it", "cancel", "not now", "ok"];
      let clicked = false;

      for (const word of dismissWords) {
        for (let i = 0; i < btnCount; i++) {
          const text = ((await buttons.nth(i).textContent()) || "").trim().toLowerCase();
          if (text.includes(word)) {
            console.error(`  Dismissing dialog: "${text}"`);
            await buttons.nth(i).click({ force: true });
            await page.waitForTimeout(2000);
            clicked = true;
            break;
          }
        }
        if (clicked) break;
      }

      if (!clicked) {
        // Fallback: press Escape
        await page.keyboard.press("Escape");
        await page.waitForTimeout(2000);
      }
    }
  }
}

async function resetConversation(page) {
  // Click the refresh/reset button in the test chat panel if available
  const resetBtn = page.locator('button[aria-label*="Reset"]')
    .or(page.locator('button[aria-label*="refresh"]'))
    .or(page.locator('button[aria-label*="Refresh"]'))
    .or(page.locator('button[title*="Reset"]'))
    .or(page.locator('button[data-telemetry-id*="reset"]'))
    .first();

  if ((await resetBtn.count()) > 0 && (await resetBtn.isVisible())) {
    await resetBtn.click({ force: true });
    await page.waitForTimeout(3000);
  }
}

async function sendAndCapture(page, utterance, testName) {
  const input = page
    .locator('textarea[placeholder*="Ask a question"]')
    .or(page.locator('textarea[placeholder*="Type"]'))
    .or(page.locator("textarea.text-area-input"))
    .first();

  await input.waitFor({ state: "visible", timeout: 15000 });

  // Count existing bot messages BEFORE sending
  const botMsgSelector = '.part-grouping-decorator--from-bot';
  const beforeCount = await page.locator(botMsgSelector).count();
  console.error(`  Messages before send: ${beforeCount}`);

  // Send the utterance
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

  // Wait for a NEW bot message to appear (count increases)
  // Skip intermediate "Generating plan..." / "Thinking..." messages
  let responseText = "";
  const maxWait = 60000;
  const start = Date.now();
  const intermediatePatterns = ["generating plan", "thinking", "planning"];

  while (Date.now() - start < maxWait) {
    await page.waitForTimeout(3000);

    // Dismiss any dialog that appeared mid-test (feedback, telemetry, etc.)
    // Check for both fui-DialogSurface and any visible overlay/modal
    await dismissDialogs(page);

    // Also try direct button clicks for known popups
    const feedbackNo = page.locator('button:has-text("No, don")').first();
    if ((await feedbackNo.count()) > 0 && (await feedbackNo.isVisible().catch(() => false))) {
      console.error("  Dismissing feedback dialog...");
      await feedbackNo.click({ force: true });
      await page.waitForTimeout(1000);
    }
    const cancelBtn = page.locator('button:has-text("Cancel")').first();
    if ((await cancelBtn.count()) > 0 && (await cancelBtn.isVisible().catch(() => false))) {
      await cancelBtn.click({ force: true });
      await page.waitForTimeout(1000);
    }

    const afterCount = await page.locator(botMsgSelector).count();
    if (afterCount > beforeCount) {
      // New message(s) appeared — grab the last one
      const lastBot = page.locator(botMsgSelector).nth(afterCount - 1);
      let rawText = ((await lastBot.textContent()) || "").trim();

      // Clean up the response text — remove UI chrome
      rawText = rawText
        .replace(/Bot said:/g, "")
        .replace(/LikeDislike/g, "")
        .replace(/Sent at .*?(Just now|ago|AM|PM)/gi, "")
        .replace(/Message is interactive.*$/g, "")
        .trim();

      // Skip intermediate planning messages — keep waiting for real response
      const isIntermediate = intermediatePatterns.some(p => rawText.toLowerCase().includes(p));
      if (isIntermediate && Date.now() - start < maxWait - 5000) {
        console.error(`  Intermediate message: "${rawText.slice(0, 50)}" — waiting for real response...`);
        continue;
      }

      responseText = rawText;
      console.error(`  Response captured (${afterCount - beforeCount} new msgs)`);
      break;
    }
  }

  if (!responseText) {
    console.error("  No bot message after 60s");
    // Take diagnostic screenshot
    await page.screenshot({
      path: path.join(diagDir, `${testName.replace(/[^a-zA-Z0-9]/g, "-")}-timeout.png`),
      fullPage: true,
    });
  }

  // Screenshot
  const safeName = testName.replace(/[^a-zA-Z0-9]/g, "-");
  await page.screenshot({
    path: path.join(diagDir, `${safeName}.png`),
  });

  return responseText;
}

(async () => {
  if (!fs.existsSync(diagDir)) fs.mkdirSync(diagDir, { recursive: true });

  const browser = await chromium.launch({ headless: !headed && hasAuth });
  const context = hasAuth
    ? await browser.newContext({ storageState: authPath })
    : await browser.newContext();
  const page = await context.newPage();
  page.setDefaultTimeout(60000);

  // Navigate
  await page.goto(URL, { waitUntil: "domcontentloaded", timeout: 30000 });
  await page.waitForTimeout(3000);

  // Auth
  if (!page.url().includes("copilotstudio.microsoft.com")) {
    console.error("AUTH REQUIRED — sign in in the browser...");
    await page.waitForURL("**/copilotstudio.microsoft.com/**", {
      timeout: 180000, waitUntil: "domcontentloaded",
    });
    const authDir = path.dirname(authPath);
    if (!fs.existsSync(authDir)) fs.mkdirSync(authDir, { recursive: true });
    await context.storageState({ path: authPath });
  }

  await page.waitForLoadState("networkidle");
  await page.waitForTimeout(3000);

  // Dismiss onboarding
  await dismissDialogs(page);

  // Ensure test panel is open
  const input = page.locator('textarea[placeholder*="Ask a question"]')
    .or(page.locator("textarea.text-area-input")).first();
  const panelOpen = (await input.count()) > 0 && (await input.isVisible().catch(() => false));

  if (!panelOpen) {
    const testBtn = page.locator('button[data-telemetry-id="test-chat-button"]')
      .or(page.locator('button:has-text("Test")')).first();
    if ((await testBtn.count()) > 0) {
      await testBtn.click({ force: true });
      await page.waitForTimeout(5000);
    }
  }

  // Run all test cases
  const results = [];
  let passed = 0;
  let failed = 0;

  for (const tc of testCases) {
    console.error(`\n--- Testing: ${tc.name} ---`);
    console.error(`  Sending: "${tc.utterance}"`);

    try {
      const response = await sendAndCapture(page, tc.utterance, tc.name);
      const responseLower = response.toLowerCase();

      let status = "PASS";
      let failReason = "";

      // Check expectContains
      if (tc.expectContains && !responseLower.includes(tc.expectContains.toLowerCase())) {
        status = "FAIL";
        failReason = `Expected response to contain "${tc.expectContains}"`;
      }

      // Check expectNotContains
      if (tc.expectNotContains && responseLower.includes(tc.expectNotContains.toLowerCase())) {
        status = "FAIL";
        failReason = `Response should not contain "${tc.expectNotContains}"`;
      }

      // Must have some response
      if (!response) {
        status = "FAIL";
        failReason = "No response received";
      }

      if (status === "PASS") passed++;
      else failed++;

      const result = {
        name: tc.name,
        status,
        utterance: tc.utterance,
        response: response.slice(0, 300),
        failReason,
      };
      results.push(result);

      console.error(`  ${status}: ${response.slice(0, 150)}`);
      if (failReason) console.error(`  REASON: ${failReason}`);
    } catch (err) {
      failed++;
      results.push({
        name: tc.name,
        status: "ERROR",
        utterance: tc.utterance,
        response: "",
        failReason: err.message,
      });
      console.error(`  ERROR: ${err.message}`);
    }
  }

  await browser.close();

  // Output summary
  const summary = {
    total: testCases.length,
    passed,
    failed,
    results,
  };

  console.log(JSON.stringify(summary, null, 2));
  process.exit(failed > 0 ? 1 : 0);
})().catch((err) => {
  console.error("Fatal:", err.message);
  process.exit(1);
});
