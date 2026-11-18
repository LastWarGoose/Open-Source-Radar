import { expect, test } from "@playwright/test";

const names = ["alpha", "beta", "gamma", "delta", "epsilon"].map((name) => "radar-stage4-" + name);

test("catalog links reach search after the landing page streams", async ({ page }) => {
  await page.setViewportSize({ width: 360, height: 800 });
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Каталог библиотек Python" })).toBeInViewport();
  const search = page.getByRole("searchbox", { name: "Поиск", exact: true });
  await page.getByRole("link", { name: "Перейти к поиску" }).click();
  await expect(search).toBeInViewport();
  await page.reload();
  await expect(search).toBeInViewport();
  await page.goto("/compare");
  await page.getByRole("link", { name: "Открыть каталог" }).click();
  await expect(page).toHaveURL(/#catalog$/);
  await expect(search).toBeInViewport();
  const sort = page.getByRole("combobox", { name: "Сортировка", exact: true });
  await expect(sort).toHaveValue("STARS_DESC");
  const relevance = sort.locator('option[value="RELEVANCE"]');
  await expect(relevance).toBeDisabled();
  await search.fill("fastapi");
  await expect(relevance).toBeEnabled();
  await sort.selectOption("RELEVANCE");
  await search.press("Enter");
  await expect(page).toHaveURL(/q=fastapi/);
  await expect(search).toBeInViewport();
  await page.mouse.move(160, 400);
  await page.mouse.wheel(0, -2500);
  await expect(page.locator(".masthead-word")).toBeInViewport();
});

test("RADAR letters grow independently and header dividers meet the hero grid", async ({
  page,
}) => {
  await page.goto("/");
  const letter = page.locator(".masthead-letter").nth(2);
  const neighbor = page.locator(".masthead-letter").nth(1);
  const width = () => letter.evaluate((node) => node.getBoundingClientRect().width);
  await expect(letter).toBeVisible();
  await page.evaluate(() => document.fonts.ready.then(() => undefined));
  const initial = await width();
  await letter.locator("..").hover();
  await expect.poll(width).toBeGreaterThan(initial * 1.05);
  await expect(neighbor).toHaveCSS("transform", "none");
  await page.locator(".site-header .brand").hover();
  await expect(letter).toHaveCSS("transform", "none");
  for (const width of [1441, 920, 639, 360]) {
    await page.setViewportSize({ width, height: 800 });
    const aligned = await page.evaluate(() => {
      const sectors = [...document.querySelectorAll(".intro-sectors > span")]
        .filter((node) => node.getClientRects().length)
        .map((node) => node.getBoundingClientRect().left);
      return [...document.querySelectorAll(".site-header nav a")].every((node) =>
        sectors.some((x) => Math.abs(x - node.getBoundingClientRect().left) < 1),
      );
    });
    expect(aligned).toBe(true);
  }
});

test("catalog SSR, filters, global sort, cursor and browser history", async ({ page, request }) => {
  const html = await (await request.get("/?q=radar-stage4-")).text();
  expect(html).toContain(names[0]);
  expect(html).toContain('rel="canonical"');
  await page.goto("/?q=radar-stage4-&size=1");
  await expect(page.locator('[data-testid="catalog-package"]:visible')).toHaveCount(1);
  await expect(page.locator('[data-testid="catalog-package"]:visible')).toContainText(names[1]);
  await page.getByRole("link", { name: "Далее →", exact: true }).click();
  await expect(page).toHaveURL(/after=/);
  await expect(page.locator('[data-testid="catalog-package"]:visible')).toContainText(names[0]);
  await page.reload();
  await expect(page.getByLabel("Сортировка")).toHaveValue("STARS_DESC");
  await expect(page.locator('[data-testid="catalog-package"]:visible')).toContainText(names[0]);
  await page.goBack();
  await expect(page.locator('[data-testid="catalog-package"]:visible')).toContainText(names[1]);
  await page.getByRole("combobox", { name: "Лицензия", exact: true }).selectOption("MIT");
  await page.getByRole("button", { name: "Найти", exact: true }).click();
  await expect(page).toHaveURL(/license=MIT/);
  await expect(page).not.toHaveURL(/after=/);
  await expect(page.locator('[data-testid="catalog-package"]:visible')).toContainText(names[0]);
  await page.getByRole("combobox", { name: "Версии", exact: true }).selectOption("no");
  await page.getByRole("button", { name: "Найти", exact: true }).click();
  await expect(page.locator('[data-testid="catalog-package"]:visible')).toContainText(names[4]);
  await page.getByLabel("Поиск", { exact: true }).fill("no-such-stage4-package");
  await page.getByRole("button", { name: "Найти", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Пакеты не найдены" })).toBeVisible();
  await page.goto("/?after=invalid");
  await expect(page.getByRole("heading", { name: "Страница устарела" })).toBeVisible();
});

test("package versions, requirements, OSV states, metadata and missing package", async ({
  page,
}) => {
  await page.goto(`/packages/${names[0]}`);
  await expect(page).toHaveTitle(new RegExp(names[0]));
  await expect(page.locator('link[rel="canonical"]')).toHaveAttribute(
    "href",
    `http://localhost:3000/packages/${names[0]}`,
  );
  await expect(page.getByRole("heading", { name: "Версия 21.0", exact: true })).toBeVisible();
  await expect(page.locator(".repo-summary")).toContainText(`Source repository for ${names[0]}.`);
  await expect(page.locator(".version-list")).not.toContainText("99.0");
  await expect(page.locator(".dependency-list li")).toHaveCount(20);
  await expect(page.locator(".dependency-list")).toContainText('python_version < "3.13"');
  await expect(page.getByText("Совпадений не найдено.")).toBeVisible();
  await expect(page.locator(".scan-result")).toContainText("Исправлено в 2.1");
  await page.getByRole("link", { name: "Ещё зависимости →" }).click();
  await expect(page.locator(".dependency-list li")).toHaveCount(5);
  await expect(page).toHaveURL(/version=21.0/);
  await page.getByRole("link", { name: "Ещё версии →" }).click();
  await page.getByRole("link", { name: "1.0", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Версия 1.0", exact: true })).toBeVisible();
  await expect(page.locator(".findings")).toContainText("Исправлено в 2.1");
  await expect(page.getByText("Последнее обновление OSV не удалось")).toBeVisible();
  await page.goto(`/packages/${names[0]}?version=2.0`);
  await expect(page.locator(".scan-result")).toContainText("Ближайшая проверенная — 1.0");
  await expect(page.locator(".findings")).toContainText("Исправлено в 2.1");
  await page.goto(`/packages/${names[1]}`);
  await expect(page.locator(".findings")).toContainText("TEST-RADAR-STAGE4-ALIAS");
  await expect(page.getByText("Последнее обновление не удалось")).toBeVisible();
  await page.goto(`/packages/${names[2]}`);
  await expect(page.getByText("Проверка не завершена.")).toBeVisible();
  await page.goto(`/packages/${names[3]}`);
  await expect(page.getByText("Эта версия ещё не проверена.")).toBeVisible();
  await page.goto(`/packages/${names[4]}`);
  await expect(page.getByRole("heading", { name: "Версии пока не загружены" })).toBeVisible();
  await page.goto(`/packages/${names[0]}?version=99.0`);
  await expect(page.getByText(/Для версии 99.0 нет данных PyPI.*21.0/)).toBeVisible();
  await page.goto("/packages/radar-stage4-hidden");
  await expect(page.getByRole("heading", { name: "Пакет или страница не найдены" })).toBeVisible();
});

test("return to a filtered page from a package version and remove a single filter", async ({
  page,
}) => {
  await page.goto("/?q=radar-stage4-&license=MIT&releases=yes&size=1&sort=NAME_ASC");
  await page.getByRole("link", { name: "Далее →", exact: true }).click();
  const result = page.getByTestId("catalog-package");
  await expect(result).toContainText(names[2]);
  const pageURL = page.url();
  await result.getByRole("link", { name: names[2], exact: true }).click();
  await page.getByRole("link", { name: "1.0", exact: true }).click();
  await expect(page).toHaveURL(/version=1\.0/);
  await page.reload();
  await page.getByRole("link", { name: "К результатам поиска" }).click();
  await expect(page).toHaveURL(pageURL);
  await expect(result).toContainText(names[2]);
  const filters = page.getByRole("navigation", { name: "Активные фильтры" });
  await filters.getByRole("link", { name: "Убрать фильтр «Лицензия · MIT»" }).click();
  await expect(page).not.toHaveURL(/license=|after=/);
  await expect(page.getByLabel("Поиск", { exact: true })).toHaveValue("radar-stage4-");
  await expect(page.getByRole("combobox", { name: "Версии", exact: true })).toHaveValue("yes");
  await expect(page.getByRole("combobox", { name: "Сортировка", exact: true })).toHaveValue(
    "NAME_ASC",
  );
  await expect(result).toHaveCount(1);
});

test("comparison cap, persistence, shared URL, removal and invalid input", async ({
  page,
  context,
}) => {
  await page.goto("/?q=radar-stage4-");
  for (const name of names.slice(0, 4)) {
    const button = page.getByRole("button", { name: `Сравнить ${name}`, exact: true });
    await button.click();
    await expect(button).toHaveAttribute("aria-pressed", "true");
  }
  await page.getByRole("button", { name: `Сравнить ${names[4]}`, exact: true }).click();
  await expect(page.getByRole("alert").filter({ hasText: "Не более 4 пакетов" })).toBeVisible();
  await page.reload();
  await expect(
    page.getByRole("button", { name: `Сравнить ${names[0]}`, exact: true }),
  ).toHaveAttribute("aria-pressed", "true");
  await page.getByRole("link", { name: "Сравнить →", exact: true }).click();
  await expect(page.locator("thead th")).toHaveCount(5);
  await expect(page.getByRole("table")).toContainText(`Source repository for ${names[0]}.`);
  const toggle = page.getByRole("checkbox", { name: "Скрыть строки с одинаковыми значениями" });
  await expect(page.getByRole("rowheader", { name: "Python", exact: true })).toBeVisible();
  await toggle.click();
  await expect(toggle).toBeChecked();
  await expect(page.getByRole("rowheader", { name: "Python", exact: true })).toHaveCount(0);
  await expect(page.getByRole("rowheader", { name: "Лицензия" })).toBeVisible();
  await page.goBack();
  await expect(toggle).not.toBeChecked();
  await toggle.click();
  // Exercise the manual sharing path even on runners without clipboard access.
  await page.evaluate(() => {
    Object.defineProperty(navigator, "clipboard", { value: undefined, configurable: true });
  });
  await page.getByRole("button", { name: "Скопировать ссылку на сравнение" }).click();
  const sharedURL = await page.getByRole("textbox", { name: "Ссылка на сравнение" }).inputValue();
  expect(sharedURL).toBe(page.url());
  const shared = await context.newPage();
  await shared.goto(sharedURL);
  await expect(shared.locator("thead th")).toHaveCount(5);
  await expect(
    shared.getByRole("checkbox", { name: "Скрыть строки с одинаковыми значениями" }),
  ).toBeChecked();
  await expect(shared.getByRole("rowheader", { name: "Python", exact: true })).toHaveCount(0);
  await expect(shared.getByRole("table")).toContainText("Найдено: 1");
  await expect(shared.getByRole("table")).toContainText(
    "Для версии 1.1 нет проверки. Ближайшая проверенная — 1.0.",
  );
  await expect(
    shared
      .getByRole("cell")
      .filter({ hasText: "Найдено: 1" })
      .getByText("Исправлено в 1.2", { exact: true }),
  ).toBeVisible();
  await page.getByRole("link", { name: `Удалить ${names[0]} из сравнения` }).click();
  await expect(page.locator("thead th")).toHaveCount(4);
  await expect(toggle).toBeChecked();
  await page.goto("/compare?packages=" + names.join(","));
  await expect(page.getByRole("heading", { name: "Можно сравнить до 4 пакетов" })).toBeVisible();
  await page.goto("/compare?packages=radar-does-not-exist");
  await expect(page.getByRole("table")).toContainText("Пакет не найден");
});

test("responsive layout, keyboard focus and browser console", async ({ page }, testInfo) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  for (const width of [1440, 768, 360]) {
    await page.setViewportSize({ width, height: 1000 });
    for (const [label, url] of [
      ["catalog", "/?q=radar-stage4-"],
      ["package", `/packages/${names[0]}`],
      ["compare", "/compare?packages=" + names.slice(0, 4).join(",")],
    ]) {
      await page.goto(url);
      await expect(page.locator("h1")).toBeVisible();
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
        true,
      );
      await page.screenshot({ path: testInfo.outputPath(`${label}-${width}.png`), fullPage: true });
    }
  }
  await page.goto("/?q=radar-stage4-");
  // The shared layout streams before the form; exercise keyboard input once it is ready.
  await expect(page.getByRole("searchbox", { name: "Поиск", exact: true })).toBeVisible();
  await page.keyboard.press("Tab");
  await expect(page.getByRole("link", { name: "К содержимому" })).toBeFocused();
  const outline = await page
    .locator(":focus")
    .evaluate((element) => getComputedStyle(element).outlineStyle);
  expect(outline).not.toBe("none");
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/#content$/);
  await expect(page.locator("#content")).toBeFocused();
  await page.keyboard.press("Tab");
  await expect(page.getByRole("link", { name: "Перейти к поиску" })).toBeFocused();
  await page.keyboard.press("Tab");
  await expect(page.getByRole("searchbox", { name: "Поиск", exact: true })).toBeFocused();
  await page.keyboard.press("Control+A");
  await page.keyboard.type(names[0]);
  await expect(page.getByRole("searchbox", { name: "Поиск", exact: true })).toHaveValue(names[0]);
  await page.keyboard.press("Enter");
  await expect(page.locator('[data-testid="catalog-package"]:visible')).toHaveCount(1);
  // Reflow equivalent of 200% browser zoom at a 1440px window.
  await page.setViewportSize({ width: 720, height: 450 });
  await page.screenshot({ path: testInfo.outputPath("catalog-reflow-200.png"), fullPage: true });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  expect(errors).toEqual([]);
});
