import { expect, test } from "@playwright/test";

test("SSR, Apollo mutation, federated subscription and reconnect", async ({
  page,
  request,
  context,
}) => {
  const response = await request.get("/demo");
  expect(response.ok()).toBeTruthy();
  const html = await response.text();
  expect(html).toContain("strawberry-graphql/strawberry");
  expect(html).toContain("fastapi/fastapi");

  const browserErrors: string[] = [];
  const graphqlURLs = new Set<string>();
  page.on("pageerror", (error) => browserErrors.push(error.message));
  page.on("request", (request) => {
    if (request.url().includes("/graphql")) graphqlURLs.add(request.url());
  });
  await page.goto("/demo");
  await expect(page.getByTestId("ssr-package")).toHaveCount(2);
  await page.locator("summary").click();
  await expect(page.getByTestId("event-repository")).toHaveText("fastapi/fastapi");
  const initial = Number(await page.getByTestId("event-revision").textContent());
  await page.getByRole("button", { name: "Обновить", exact: true }).click();
  await expect(page.getByTestId("event-revision")).toHaveText(String(initial + 1));
  await expect(page.getByTestId("query-revision")).toHaveText(String(initial + 1));

  // Unsubscribe, mutate while offline from events, then restore with a fresh query.
  await page.getByRole("button", { name: "Пауза", exact: true }).click();
  await expect(page.locator("summary").getByRole("status")).toHaveText("Пауза");
  await page.getByRole("button", { name: "Обновить", exact: true }).click();
  await expect(page.getByTestId("query-revision")).toHaveText(String(initial + 2));
  await expect(page.getByTestId("event-revision")).toHaveText(String(initial + 1));
  await page.getByRole("button", { name: "Продолжить", exact: true }).click();
  await expect(page.getByTestId("event-revision")).toHaveText(String(initial + 2));

  // Real network interruption: the graphql-ws client must reconnect automatically.
  await context.setOffline(true);
  const mutation = await request.post("http://localhost:4000/graphql", {
    data: {
      query: "mutation OfflineUpdate($id: ID!) { advanceDemo(id: $id) { demoRevision } }",
      variables: { id: "pypi:fastapi" },
    },
  });
  expect((await mutation.json()).errors).toBeUndefined();
  await context.setOffline(false);
  await expect(page.getByTestId("event-revision")).toHaveText(String(initial + 3), {
    timeout: 20_000,
  });
  await expect(page.getByTestId("query-revision")).toHaveText(String(initial + 3));
  expect([...graphqlURLs]).toEqual(["http://localhost:4000/graphql"]);
  expect(browserErrors).toEqual([]);

  await page.setViewportSize({ width: 360, height: 800 });
  expect(
    await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth),
  ).toBeTruthy();
  await page.screenshot({ path: "test-results/stage0-mobile.png", fullPage: true });
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.screenshot({ path: "test-results/stage0-desktop.png", fullPage: true });
});
