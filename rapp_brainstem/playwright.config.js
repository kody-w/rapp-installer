// @ts-check
const { defineConfig } = require("@playwright/test");

module.exports = defineConfig({
  testDir: "./tests",
  testMatch: "copilot_studio_test.js",
  timeout: 120000, // 2 min per test (Copilot Studio can be slow)
  retries: 0,
  workers: 1, // Sequential — single browser session
  reporter: [["list"], ["html", { open: "never" }]],
  use: {
    browserName: "chromium",
    headless: false, // Must be headed for first auth; set true after .auth/state.json exists
    viewport: { width: 1440, height: 900 },
    actionTimeout: 30000,
    screenshot: "on",
    trace: "retain-on-failure",
  },
});
