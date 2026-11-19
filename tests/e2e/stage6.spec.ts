import { test, expect } from "@playwright/test";

const run = process.env.STAGE6_RUN;
const password = process.env.STAGE6_PASSWORD!;
test.skip(!run, "Run via scripts.verify_stage6 for isolated accounts and paused consumers");
test.use({ trace: "off", video: "off" }); // Never retain authentication inputs or recovery codes.
test.setTimeout(120_000);

test("registration, collections, follow, logout and recovery", async ({
  page,
  context,
}, testInfo) => {
  await page.goto("/account");
  await page.getByRole("button", { name: "Регистрация", exact: true }).click();
  await page.getByLabel("Логин", { exact: true }).fill(run + "a");
  await page.getByLabel("Пароль", { exact: true }).fill(password);
  await page.getByRole("button", { name: "Создать аккаунт" }).click();
  const code = await page.getByTestId("recovery-code").textContent();
  expect(code).toBeTruthy();
  const cookies = await context.cookies();
  const session = cookies.find((c) => c.name === "radar_session");
  expect(session?.httpOnly).toBe(true);
  expect(session?.sameSite).toBe("Strict");
  expect(await page.evaluate(() => document.cookie.includes("radar_session"))).toBe(false);
  await page.getByRole("link", { name: "Код сохранён" }).click();
  await expect(page.getByLabel("Название подборки")).toHaveCount(0);
  const createCollection = page.getByRole("button", { name: "Создать подборку", exact: true });
  await createCollection.click();
  const dialog = page.getByRole("dialog");
  await expect(dialog.getByLabel("Название подборки")).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(dialog).toHaveCount(0);
  await createCollection.click();
  await dialog.getByLabel("Название подборки").fill("Мои библиотеки");
  await dialog.getByRole("button", { name: "Создать", exact: true }).click();
  const collection = page.getByRole("button", { name: "Мои библиотеки", exact: true });
  await expect(collection).toHaveAttribute("aria-expanded", "true");
  await collection.click();
  await expect(collection).toHaveAttribute("aria-expanded", "false");
  await collection.click();
  await expect(page.getByRole("button", { name: /Удалить подборку/ })).toHaveCount(0);
  await page.getByRole("button", { name: "Действия", exact: true }).click();
  await expect(page.getByRole("button", { name: "Удалить подборку Мои библиотеки" })).toBeVisible();
  await page.getByRole("heading", { name: "Подборки", exact: true }).click();
  await expect(collection).toHaveAttribute("aria-expanded", "false");
  await collection.focus();
  await page.keyboard.press("Enter");
  await expect(collection).toHaveAttribute("aria-expanded", "true");
  await page.keyboard.press("Escape");
  await expect(collection).toHaveAttribute("aria-expanded", "false");
  await expect(collection).toBeFocused();
  await createCollection.click();
  await dialog.getByLabel("Название подборки").fill("Временная");
  await dialog.getByRole("button", { name: "Создать", exact: true }).click();
  await page.getByRole("button", { name: "Действия", exact: true }).click();
  await page.getByRole("button", { name: "Удалить подборку Временная", exact: true }).click();
  await expect(page.getByRole("button", { name: "Временная", exact: true })).toHaveCount(0);
  await expect(collection).toBeVisible();
  await page.goto(`/?q=${run}-package#catalog`);
  const actions = page.getByRole("group", { name: `Действия с ${run}-package` });
  await actions.getByRole("button", { name: "В подборку", exact: true }).click();
  await page
    .getByRole("combobox", { name: "Подборка", exact: true })
    .selectOption({ label: "Мои библиотеки" });
  await page.getByRole("button", { name: "Сохранить", exact: true }).click();
  await expect(page.locator(".toast")).toContainText("добавлен в подборку");
  await actions.getByRole("button", { name: "Отслеживать", exact: true }).click();
  await expect(actions.getByRole("button", { name: "Отслеживается", exact: true })).toHaveAttribute(
    "aria-pressed",
    "true",
  );
  await page.goto(`/packages/${run}-package`);
  await expect(actions.getByRole("button", { name: "Отслеживается", exact: true })).toBeVisible();
  await page.goto("/account");
  await page.getByRole("button", { name: "Мои библиотеки", exact: true }).click();
  await expect(page.getByRole("link", { name: `${run}-package`, exact: true })).toBeVisible();
  await page.getByRole("link", { name: "Отслеживание", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Отслеживание", exact: true })).toBeVisible();
  await expect(page.getByRole("link", { name: `${run}-package`, exact: true })).toBeVisible();
  await page.getByRole("link", { name: "Уведомления", exact: true }).click();
  await expect(page).toHaveURL(/section=notifications$/);
  await page.reload();
  await expect(page.getByRole("link", { name: "Уведомления", exact: true })).toHaveAttribute(
    "aria-current",
    "page",
  );
  await page.getByRole("link", { name: "Подборки", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Подборки", exact: true })).toBeVisible();
  await page.screenshot({
    path: testInfo.outputPath("personal-desktop.png"),
    fullPage: true,
    animations: "disabled",
  });
  await page.setViewportSize({ width: 360, height: 800 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({
    path: testInfo.outputPath("personal-mobile.png"),
    fullPage: true,
    animations: "disabled",
  });
  await page.getByRole("button", { name: "Выйти", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Вход", exact: true })).toBeVisible();
  await page.getByLabel("Логин", { exact: true }).fill(run + "b");
  await page.getByLabel("Пароль", { exact: true }).fill(password);
  await page.getByRole("button", { name: "Войти", exact: true }).click();
  await expect(page.getByRole("button", { name: "Создать подборку", exact: true })).toBeVisible();
  await expect(collection).toHaveCount(0);
  await expect(page.getByText("Мои библиотеки", { exact: true })).toHaveCount(0);
  await page.getByRole("button", { name: "Выйти", exact: true }).click();
  await page.getByRole("button", { name: "Забыли пароль?" }).click();
  await page.getByLabel("Логин", { exact: true }).fill(run + "a");
  await page.getByLabel("Код восстановления", { exact: true }).fill(code!);
  await page.getByLabel("Новый пароль", { exact: true }).fill(password + "-new");
  await page.getByRole("button", { name: "Сменить пароль", exact: true }).click();
  await expect(page.getByTestId("recovery-code")).toBeVisible();
  await page.getByRole("link", { name: "Код сохранён" }).click();
  await page.getByLabel("Логин", { exact: true }).fill(run + "a");
  await page.getByLabel("Пароль", { exact: true }).fill(password + "-new");
  await page.getByRole("button", { name: "Войти", exact: true }).click();
  await expect(page.getByRole("button", { name: "Мои библиотеки", exact: true })).toBeVisible();
});

test("admin import, persisted job after reload, user denied", async ({ page }, testInfo) => {
  // Pin only the request UUID to let fixture cleanup identify this run's job exactly.
  await page.addInitScript((key) => {
    crypto.randomUUID = () => key as `${string}-${string}-${string}-${string}-${string}`;
  }, process.env.STAGE6_JOB_KEY!);
  await page.goto("/account");
  await page.getByLabel("Логин", { exact: true }).fill(run + "admin");
  await page.getByLabel("Пароль", { exact: true }).fill(password);
  await page.getByRole("button", { name: "Войти", exact: true }).click();
  await page.getByRole("link", { name: "Импорт", exact: true }).click();
  await page.getByLabel("Пакеты PyPI — до 20").fill(`${run}-package`);
  await page.getByRole("button", { name: "Запустить импорт" }).click();
  await expect(page.getByRole("region", { name: "Прогресс импорта" })).toContainText("В очереди");
  await page.screenshot({ path: testInfo.outputPath("admin.png"), fullPage: true });
  await page.reload();
  await expect(page.getByRole("button", { name: /PYPI · В очереди · 0/ }).first()).toBeVisible();
  await page.goto("/account");
  await page.getByRole("button", { name: "Выйти", exact: true }).click();
  await page.getByLabel("Логин", { exact: true }).fill(run + "b");
  await page.getByLabel("Пароль", { exact: true }).fill(password);
  await page.getByRole("button", { name: "Войти", exact: true }).click();
  await expect(page.getByRole("heading", { name: run + "b", exact: true })).toBeVisible();
  await page.goto("/admin");
  await expect(page.getByText("Доступ только администратору.", { exact: true })).toBeVisible();
});
