/**
 * Playwright test: RAPP Brainstem agent in Copilot Studio Test Chat
 *
 * Tests the draft agent directly in the Copilot Studio UI.
 * Requires the user to be logged into copilotstudio.microsoft.com
 * (uses saved browser state from auth profile).
 *
 * Usage:
 *   npx playwright test tests/copilot_studio_test.js
 *   npx playwright test tests/copilot_studio_test.js --headed   (watch it run)
 *
 * First run: use --headed to sign in manually. The auth state is saved
 * to tests/.auth/ for subsequent headless runs.
 */

const { test, expect } = require("@playwright/test");
const path = require("path");
const fs = require("fs");

// Load connection info
const connPath = path.join(
  __dirname,
  "..",
  "copilot-studio",
  "RAPP Brainstem",
  ".mcs",
  "conn.json"
);
const conn = JSON.parse(fs.readFileSync(connPath, "utf-8"));

const ENV_ID = conn.EnvironmentId;
const AGENT_ID = conn.AgentId;
const COPILOT_STUDIO_URL = `https://copilotstudio.microsoft.com/environments/${ENV_ID}/bots/${AGENT_ID}/topics`;

const AUTH_STATE_PATH = path.join(__dirname, ".auth", "state.json");

// Test utterances and expected behaviors
const TEST_CASES = [
  {
    name: "Greeting",
    utterance: "Hi there!",
    expectContains: null, // Any response is fine for greeting
    expectNoError: true,
  },
  {
    name: "HackerNews topic trigger",
    utterance: "Show me what's on Hacker News",
    expectContains: "Hacker News",
    expectNoError: true,
  },
  {
    name: "SaveMemory topic trigger",
    utterance: "Remember that my favorite color is blue",
    expectContains: null, // Should trigger save flow
    expectNoError: true,
  },
  {
    name: "RecallMemory topic trigger",
    utterance: "What do you remember about me?",
    expectContains: null, // Should trigger recall flow
    expectNoError: true,
  },
  {
    name: "OnlineResearch topic trigger",
    utterance: "Research the latest news about AI agents",
    expectContains: null,
    expectNoError: true,
  },
];

// Helper: wait for the test chat panel's response
async function waitForBotResponse(page, timeout = 30000) {
  // The test chat panel renders bot messages in elements with specific patterns
  // Wait for a new bot message to appear after sending
  const startTime = Date.now();

  // Wait for the typing indicator to appear and then disappear
  try {
    await page.waitForSelector(
      '[class*="typing"], [class*="Typing"], [data-testid*="typing"]',
      { timeout: 5000 }
    );
  } catch {
    // Typing indicator might not show, that's ok
  }

  // Wait for it to disappear (bot finished responding)
  try {
    await page.waitForFunction(
      () => {
        const typing = document.querySelectorAll(
          '[class*="typing"], [class*="Typing"], [data-testid*="typing"]'
        );
        return typing.length === 0;
      },
      { timeout: timeout }
    );
  } catch {
    // May have already disappeared
  }

  // Small buffer for rendering
  await page.waitForTimeout(1500);
}

// Helper: get all bot messages from the test chat
async function getBotMessages(page) {
  return await page.evaluate(() => {
    // Copilot Studio test chat renders messages in a chat container
    // Bot messages typically have aria labels or specific classes
    const messages = [];

    // Try multiple selectors for bot messages
    const selectors = [
      '[class*="bot-message"]',
      '[class*="BotMessage"]',
      '[data-testid*="bot-message"]',
      '[class*="webchat"] [class*="from-bot"] [class*="content"]',
      '[class*="message--from-bot"]',
      ".webchat__bubble--from-bot .webchat__bubble__content",
      '[class*="activityContent"]',
    ];

    for (const sel of selectors) {
      const elements = document.querySelectorAll(sel);
      elements.forEach((el) => {
        const text = el.textContent?.trim();
        if (text) messages.push(text);
      });
      if (messages.length > 0) break;
    }

    // Fallback: get all text from the chat area
    if (messages.length === 0) {
      const chatArea = document.querySelector(
        '[class*="chat"], [class*="webchat"], [role="log"]'
      );
      if (chatArea) {
        messages.push(chatArea.textContent?.trim() || "");
      }
    }

    return messages;
  });
}

// Helper: send a message in the test chat
async function sendMessage(page, text) {
  // Find the input field in the test chat panel
  const inputSelectors = [
    '[class*="webchat"] textarea',
    '[class*="webchat"] input[type="text"]',
    '[data-testid*="sendbox"] textarea',
    '[data-testid*="sendbox"] input',
    'textarea[placeholder*="Type"]',
    'input[placeholder*="Type"]',
    '[class*="send-box"] textarea',
    '[class*="send-box"] input',
    '[class*="SendBox"] textarea',
    '[class*="SendBox"] input',
  ];

  let input = null;
  for (const sel of inputSelectors) {
    input = await page.$(sel);
    if (input) break;
  }

  if (!input) {
    throw new Error("Could not find test chat input field");
  }

  await input.fill(text);

  // Press Enter or click send button
  const sendSelectors = [
    'button[class*="send"]',
    'button[aria-label*="Send"]',
    'button[title*="Send"]',
    '[class*="webchat"] button[type="submit"]',
  ];

  let sendButton = null;
  for (const sel of sendSelectors) {
    sendButton = await page.$(sel);
    if (sendButton) break;
  }

  if (sendButton) {
    await sendButton.click();
  } else {
    await input.press("Enter");
  }
}

// Setup: authenticate with Copilot Studio
test.describe("RAPP Brainstem — Copilot Studio Test Chat", () => {
  let page;

  test.beforeAll(async ({ browser }) => {
    // Try to reuse saved auth state
    let context;
    if (fs.existsSync(AUTH_STATE_PATH)) {
      context = await browser.newContext({ storageState: AUTH_STATE_PATH });
    } else {
      context = await browser.newContext();
    }

    page = await context.newPage();
    page.setDefaultTimeout(60000);

    // Navigate to Copilot Studio
    console.log(`Navigating to: ${COPILOT_STUDIO_URL}`);
    await page.goto(COPILOT_STUDIO_URL, { waitUntil: "domcontentloaded" });

    // Check if we need to sign in
    const currentUrl = page.url();
    if (
      currentUrl.includes("login.microsoftonline.com") ||
      currentUrl.includes("login.live.com")
    ) {
      console.log("Authentication required — waiting for manual sign-in...");
      console.log("Please sign in in the browser window.");

      // Wait for redirect back to Copilot Studio (up to 2 minutes for manual login)
      await page.waitForURL("**/copilotstudio.microsoft.com/**", {
        timeout: 120000,
      });
      console.log("Sign-in complete.");

      // Save auth state for future runs
      const authDir = path.dirname(AUTH_STATE_PATH);
      if (!fs.existsSync(authDir)) fs.mkdirSync(authDir, { recursive: true });
      await context.storageState({ path: AUTH_STATE_PATH });
      console.log(`Auth state saved to ${AUTH_STATE_PATH}`);
    }

    // Wait for the page to fully load
    await page.waitForLoadState("networkidle");
    console.log("Copilot Studio loaded.");

    // Open the Test Chat panel (click the "Test" button)
    const testButtonSelectors = [
      'button:has-text("Test")',
      'button:has-text("Test your agent")',
      '[data-testid*="test"]',
      'button[aria-label*="Test"]',
      '[class*="test-button"]',
      '[class*="TestButton"]',
    ];

    let testButton = null;
    for (const sel of testButtonSelectors) {
      testButton = await page.$(sel);
      if (testButton) break;
    }

    if (testButton) {
      await testButton.click();
      console.log("Test chat panel opened.");
      await page.waitForTimeout(3000); // Wait for panel to render
    } else {
      console.log(
        "Test button not found — test chat may already be open or UI has changed."
      );
    }
  });

  test.afterAll(async () => {
    if (page) {
      // Take a final screenshot
      await page.screenshot({
        path: path.join(__dirname, "test-results", "final-state.png"),
        fullPage: true,
      });
    }
  });

  // Run each test case
  for (const tc of TEST_CASES) {
    test(tc.name, async () => {
      console.log(`\nSending: "${tc.utterance}"`);

      const messageCountBefore = (await getBotMessages(page)).length;
      await sendMessage(page, tc.utterance);
      await waitForBotResponse(page);

      const allMessages = await getBotMessages(page);
      const newMessages = allMessages.slice(messageCountBefore);

      console.log(`Bot responded with ${newMessages.length} new message(s):`);
      newMessages.forEach((m, i) => console.log(`  [${i}] ${m.slice(0, 200)}`));

      // Take screenshot for this test case
      const screenshotDir = path.join(__dirname, "test-results");
      if (!fs.existsSync(screenshotDir))
        fs.mkdirSync(screenshotDir, { recursive: true });
      await page.screenshot({
        path: path.join(
          screenshotDir,
          `${tc.name.replace(/\s+/g, "-")}.png`
        ),
      });

      // Assertions
      if (tc.expectNoError) {
        const hasError = newMessages.some(
          (m) =>
            m.toLowerCase().includes("error") &&
            m.toLowerCase().includes("code:")
        );
        expect(hasError).toBeFalsy();
      }

      if (tc.expectContains) {
        const combined = newMessages.join(" ");
        expect(combined.toLowerCase()).toContain(
          tc.expectContains.toLowerCase()
        );
      }

      // At minimum, we should get some response
      expect(newMessages.length).toBeGreaterThan(0);
    });
  }
});
