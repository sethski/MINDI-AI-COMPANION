import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "apps/desktop/e2e",
  timeout: 60_000,
  expect: {
    timeout: 10_000,
  },
  fullyParallel: false,
  reporter: [["list"], ["html", { open: "never" }]],
  use: {
    baseURL: "http://127.0.0.1:5173",
    trace: "on-first-retry",
  },
  webServer: [
    {
      command:
        "python -m uvicorn mindi_agent.main:app --reload --host 127.0.0.1 --port 8765 --app-dir services/agent/src",
      url: "http://127.0.0.1:8765/health",
      reuseExistingServer: !process.env.CI,
      timeout: 120_000,
    },
    {
      command: "pnpm --dir apps/desktop dev --host 127.0.0.1 --port 5173",
      url: "http://127.0.0.1:5173",
      reuseExistingServer: !process.env.CI,
      timeout: 120_000,
    },
  ],
});
