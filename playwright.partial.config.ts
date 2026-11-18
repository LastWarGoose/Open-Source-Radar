import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "tests/fault",
  workers: 1,
  timeout: 45_000,
  outputDir: "test-results/partial-" + process.env.FAILED_SERVICE,
  use: { baseURL: process.env.WEB_URL ?? "http://localhost:3000", trace: "retain-on-failure" },
});
