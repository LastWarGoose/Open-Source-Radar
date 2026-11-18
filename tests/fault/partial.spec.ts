import { expect, test } from "@playwright/test";

test("public site preserves available data during an actual service outage", async ({
  page,
}, testInfo) => {
  const service = process.env.FAILED_SERVICE;
  expect(["security", "repositories", "catalog"]).toContain(service);
  if (service === "catalog") {
    await page.goto("/");
    await expect(page.getByRole("heading", { name: "Каталог недоступен" })).toBeVisible();
    await page.goto("/compare?packages=radar-stage4-alpha,radar-stage4-beta");
    await expect(page.getByRole("heading", { name: "Сравнение недоступно" })).toBeVisible();
  } else {
    await page.goto("/packages/radar-stage4-alpha");
    await expect(
      page.getByRole("heading", { name: "radar-stage4-alpha", exact: true }),
    ).toBeVisible();
    await expect(page.getByRole("heading", { name: "Версия 21.0" })).toBeVisible();
    await expect(
      page.getByText(
        service === "security"
          ? "OSV недоступен. Повторите позже."
          : "GitHub недоступен. Метаданные пакета доступны.",
      ),
    ).toBeVisible();
    await expect(page.locator(".dependency-list li")).toHaveCount(20);
    await page.screenshot({ path: testInfo.outputPath("partial.png"), fullPage: true });
    await page.goto("/compare?packages=radar-stage4-alpha,radar-stage4-beta");
    await expect(page.getByRole("table")).toContainText("21.0");
    await expect(
      page.getByText("Часть данных недоступна. Показаны доступные сведения."),
    ).toBeVisible();
    const affected = page.getByRole("row").filter({
      has: page.getByRole("rowheader", {
        name: service === "security" ? "Уязвимости OSV" : "Репозитории",
        exact: true,
      }),
    });
    await expect(
      affected.getByRole("cell", {
        name: service === "security" ? "OSV недоступен" : "GitHub недоступен",
        exact: true,
      }),
    ).toHaveCount(2);
  }
});
