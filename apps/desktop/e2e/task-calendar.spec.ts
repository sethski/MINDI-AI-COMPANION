import { expect, test, type Page } from "@playwright/test";

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

  const taskItem = page.locator("li", { hasText: title }).first();
  await expect(taskItem).toContainText("[todo]");

  await taskItem.getByRole("button", { name: "Done" }).click();
  await expect(taskItem).toContainText("[done]");

  await taskItem.getByRole("button", { name: "Reopen" }).click();
  await expect(taskItem).toContainText("[todo]");

  const matchingBeforeImport = await page.locator("li", { hasText: title }).count();

  await page.getByRole("button", { name: "Export Calendar (.ics)" }).click();
  await expect(page.locator(".assistant-reply").first()).toContainText("Calendar exported:");

  queueDialogResponses(page, ["data/runtime/exports/mindi-tasks.ics"]);
  await page.getByRole("button", { name: "Import Calendar (.ics)" }).click();
  await expect(page.locator(".assistant-reply").first()).toContainText("Calendar imported:");

  const matchingAfterImport = await page.locator("li", { hasText: title }).count();
  expect(matchingAfterImport).toBe(matchingBeforeImport);
});
