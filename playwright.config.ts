import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "tests/e2e",
  workers: 1,
  timeout: 45_000,
  use: { baseURL: process.env.WEB_URL ?? "http://localhost:3000", trace: "retain-on-failure" },
  reporter: [["list"]],
});
