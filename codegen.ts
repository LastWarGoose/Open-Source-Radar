import type { CodegenConfig } from "@graphql-codegen/cli";

const config: CodegenConfig = {
  schema: process.env.GRAPHQL_SCHEMA_URL ?? "http://localhost:4000/graphql",
  documents: ["apps/web/src/**/*.graphql"],
  generates: {
    "apps/web/src/gql/": {
      preset: "client",
      presetConfig: { fragmentMasking: false },
      config: { useTypeImports: true, scalars: { DateTime: "string", UUID: "string" } },
    },
  },
};
export default config;
