import { expect, test } from "@playwright/test";

test("starts a PVP game and shows an A-side verdict", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: /双人同屏/ }).click();

  await expect(page.getByRole("heading", { name: "抽取崩坏因子" })).toBeVisible();
  await expect(page.getByTestId("word-card")).toHaveCount(5);
  await expect(page.getByText("抽象派", { exact: true })).toHaveCount(2);

  await page.getByRole("button", { name: "违禁词：秦始皇" }).click();

  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible();
  await expect(dialog.getByTestId("judge-score")).toHaveText("88");
  await expect(dialog).toContainText("时空管理局");

  await dialog.getByRole("button", { name: "继续对局" }).click();
  await expect(page.getByText("B 方操作")).toBeVisible();
});

test("keeps the home and game screens within the viewport", async ({ page }) => {
  await page.goto("/");
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);

  await page.getByRole("button", { name: /人机对战/ }).click();
  await expect(page.getByRole("heading", { name: "抽取崩坏因子" })).toBeVisible();
  await expect(page.getByText("B 方将在本轮自动缝合")).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);

  await page.getByRole("button", { name: "违禁词：秦始皇" }).click();
  await page.getByRole("dialog").getByRole("button", { name: "继续对局" }).click();
  await expect(page.locator(".round-marker strong")).toHaveText("02");
  await expect(page.getByText("B 方已自动缝合")).toBeVisible();
});
