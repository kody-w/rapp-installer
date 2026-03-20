const { chromium } = require("playwright");
const fs = require("fs");
const path = require("path");

(async () => {
  const authPath = path.join(__dirname, ".auth", "state.json");
  const hasAuth = fs.existsSync(authPath);
  const browser = await chromium.launch({ headless: false });
  const context = hasAuth
    ? await browser.newContext({ storageState: authPath })
    : await browser.newContext();
  const page = await context.newPage();
  page.setDefaultTimeout(60000);

  const url =
    "https://copilotstudio.microsoft.com/environments/2fd4aaa7-fba5-ef77-886f-d742b3b5f51b/bots/7466922d-1048-498c-8dff-84297765cbe9/topics";
  console.log("Navigating to:", url);
  await page.goto(url, { waitUntil: "domcontentloaded", timeout: 30000 });

  // Wait a moment for any redirects
  await page.waitForTimeout(3000);

  // Handle auth — check if we landed on a login page
  const currentUrl = page.url();
  if (
    currentUrl.includes("login.microsoftonline.com") ||
    currentUrl.includes("login.live.com") ||
    !currentUrl.includes("copilotstudio.microsoft.com")
  ) {
    console.log("AUTH REQUIRED — please sign in in the browser window...");
    console.log("Waiting up to 3 minutes for sign-in...");
    await page.waitForURL("**/copilotstudio.microsoft.com/**", {
      timeout: 180000,
      waitUntil: "domcontentloaded",
    });
    // Save auth state for future runs
    const authDir = path.dirname(authPath);
    if (!fs.existsSync(authDir)) fs.mkdirSync(authDir, { recursive: true });
    await context.storageState({ path: authPath });
    console.log("Auth saved for future headless runs.");
  }

  // Wait for the SPA to fully load
  console.log("Waiting for Copilot Studio to load...");
  await page.waitForLoadState("networkidle");
  console.log("Page loaded. URL:", page.url());

  // Wait for SPA to render
  await page.waitForTimeout(8000);

  // Screenshot
  const ssDir = path.join(__dirname, "test-results");
  if (!fs.existsSync(ssDir)) fs.mkdirSync(ssDir, { recursive: true });
  await page.screenshot({
    path: path.join(ssDir, "debug-page-state.png"),
    fullPage: true,
  });
  console.log("Screenshot saved: tests/test-results/debug-page-state.png");

  // List all buttons
  const buttons = await page.locator("button").all();
  const btnTexts = [];
  for (const btn of buttons) {
    const text = await btn.textContent();
    if (text && text.trim()) btnTexts.push(text.trim().slice(0, 60));
  }
  console.log("Buttons found:", JSON.stringify(btnTexts.slice(0, 40)));

  // Try to find and click the Test button
  const testBtn = page.locator('button:has-text("Test")').first();
  if ((await testBtn.count()) > 0) {
    console.log("Found Test button, clicking...");
    await testBtn.click();
    await page.waitForTimeout(5000);
    await page.screenshot({
      path: path.join(ssDir, "debug-after-test-click.png"),
      fullPage: true,
    });
    console.log("Screenshot after test click saved.");
  } else {
    console.log("No Test button found.");
  }

  // List all input elements
  const inputs = await page.locator("textarea, input[type='text']").all();
  console.log("Input elements found:", inputs.length);
  for (const inp of inputs) {
    const ph = await inp.getAttribute("placeholder");
    const cls = await inp.getAttribute("class");
    const tag = await inp.evaluate((el) => el.tagName);
    console.log("  Input:", { tag, placeholder: ph, class: cls?.slice(0, 80) });
  }

  // Also check for iframes (test chat might be in an iframe)
  const iframes = await page.locator("iframe").all();
  console.log("Iframes found:", iframes.length);
  for (const iframe of iframes) {
    const src = await iframe.getAttribute("src");
    const title = await iframe.getAttribute("title");
    console.log("  Iframe:", { src: src?.slice(0, 120), title });
  }

  await browser.close();
})().catch((err) => {
  console.error(err.message);
  process.exit(1);
});
