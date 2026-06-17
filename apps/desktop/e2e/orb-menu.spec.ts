import { expect, test } from "@playwright/test";

test("left click on idle orb opens the orb menu", async ({ page }) => {
  await page.goto("http://localhost:5173/orb.html");

  await page.locator(".orb-idle").click();

  await expect(page.getByRole("menuitem", { name: "Open MINDI" })).toBeVisible();
  await expect(page.getByRole("menuitem", { name: "Quit MINDI" })).toBeVisible();
});
