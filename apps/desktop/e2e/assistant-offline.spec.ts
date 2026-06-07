import { expect, test } from "@playwright/test";

test("assistant surfaces degraded reply when ai runtime is not running", async ({ page }) => {
  // Playwright webServer starts agent + Vite only (no ai_runtime on :8877).
  // Avoid screen/perception keywords — those bypass LLM via memory snapshot shortcut.
  await page.goto("/");

  const input = page.getByPlaceholder("Message MINDI...");
  await input.fill("Summarize my open tasks in one sentence.");
  await input.press("Enter");

  const mindiReply = page.locator(".chat__msg--assistant .chat__msg-body").last();
  await expect(mindiReply).toBeVisible({ timeout: 20_000 });
  await expect(mindiReply).toHaveText(
    /could not run the local qwen model|Local model unavailable|Confirm agent and AI runtime/i,
  );
  await expect(page.locator(".chat__msg--assistant .chat__msg-meta").last()).toContainText(
    /degraded|runtime/i,
  );
});

test("offline chat enqueues a sync item", async ({ page, context }) => {
  await page.goto("/");
  await context.setOffline(true);

  const input = page.getByPlaceholder("Message MINDI...");
  await input.fill("offline queue probe");
  await input.press("Enter");

  await expect(page.locator(".chat__msg--assistant .chat__msg-body").last()).toHaveText(
    /queued this and will sync/i,
    { timeout: 15_000 },
  );

  const depth = await page.evaluate(() => {
    const raw = localStorage.getItem("mindi.sync_queue.v1");
    return raw ? (JSON.parse(raw) as unknown[]).length : 0;
  });
  expect(depth).toBeGreaterThan(0);
});
