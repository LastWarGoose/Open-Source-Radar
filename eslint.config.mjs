import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTypescript from "eslint-config-next/typescript";

export default defineConfig([
  ...nextVitals,
  ...nextTypescript,
  { settings: { next: { rootDir: "apps/web/" }, react: { version: "19.3" } } },
  {
    files: ["tests/load/*.js"],
    languageOptions: { globals: { __ENV: "readonly", open: "readonly" } },
  },
  globalIgnores([
    "**/node_modules/**",
    "**/.next/**",
    "apps/web/src/gql/**",
    "apps/web/next-env.d.ts",
  ]),
]);
