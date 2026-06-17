import { test } from "@playwright/test";

test("idle orb starts wake listening with mic permission", async ({ page, context }) => {
  await context.grantPermissions(["microphone"]);
  await page.goto("/orb.html");
  await page.waitForTimeout(8000);
});
