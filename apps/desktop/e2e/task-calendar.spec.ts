import * as fs from "node:fs";
import * as path from "node:path";
import { expect, test, type Page } from "@playwright/test";

const EXPORT_ICS = path.resolve("data/runtime/exports/mindi-tasks.ics");

function queueDialogResponses(page: Page, responses: string[]): void {
  let index = 0;
  const handler = async (dialog: { accept: (response?: string) => Promise<void> }) => {
    const response = responses[index] ?? "";
    index += 1;
    await dialog.accept(response);
    if (index >= responses.length) {
      page.off("dialog", handler);
    }
  };
  page.on("dialog", handler);
}

test("task status flow and calendar import dedupe", async ({ page }) => {
  await page.goto("/");

  const title = `e2e-task-${Date.now()}`;
  queueDialogResponses(page, [title, "2026-08-01T10:00:00Z", "none"]);
  await page.getByRole("button", { name: "+ Task" }).click();

  const taskItem = page.locator("li.chat-aside__task", { hasText: title }).first();
  await expect(taskItem.locator(".chat-aside__pill--todo")).toBeVisible();

  await taskItem.getByRole("button", { name: "Done" }).click();
  await expect(taskItem.locator(".chat-aside__pill--done")).toBeVisible();

  await taskItem.getByRole("button", { name: "Reopen" }).click();
  await expect(taskItem.locator(".chat-aside__pill--todo")).toBeVisible();

  const matchingBeforeImport = await page.locator("li.chat-aside__task", { hasText: title }).count();

  await page.getByRole("button", { name: "Export .ics" }).click();
  await expect.poll(() => fs.existsSync(EXPORT_ICS), { timeout: 15_000 }).toBe(true);

  queueDialogResponses(page, ["data/runtime/exports/mindi-tasks.ics"]);
  await page.getByRole("button", { name: "Import .ics" }).click();

  await expect
    .poll(async () => page.locator("li.chat-aside__task", { hasText: title }).count())
    .toBe(matchingBeforeImport);
});
