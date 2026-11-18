import { defineConfig } from "@graphql-hive/gateway";
import { getOperationAST } from "graphql";
import { controls, outbound } from "./controls.mjs";

export const gatewayConfig = defineConfig({
  supergraph: "../packages/graphql/supergraph.graphql",
  port: 4000,
  host: "0.0.0.0",
  graphqlEndpoint: "/graphql",
  maxDepth: 16,
  maxTokens: 6000,
  upstreamTimeout: ({ executionRequest }) =>
    getOperationAST(executionRequest.document, executionRequest.operationName)?.operation ===
    "subscription"
      ? undefined
      : 8000,
  plugins: () => [controls],
  propagateHeaders: {
    fromClientToSubgraphs({ request }) {
      const incoming = request.headers.get("x-request-id") ?? "";
      return {
        ...outbound(request),
        "x-request-id": /^[a-zA-Z0-9_-]{1,64}$/.test(incoming) ? incoming : crypto.randomUUID(),
        "x-dev-admin-token": request.headers.get("x-dev-admin-token") ?? "",
        "x-workspace-token": request.headers.get("x-workspace-token") ?? "",
        cookie: request.headers.get("cookie") ?? "",
        origin: request.headers.get("origin") ?? "",
      };
    },
    fromSubgraphsToClient({ response }) {
      const cookie = response.headers.get("set-cookie");
      return { ...(cookie ? { "set-cookie": cookie } : {}), "cache-control": "no-store, private" };
    },
  },
  cors: {
    origin: [
      "http://localhost:3000",
      "http://127.0.0.1:3000",
      ...(process.env.SITE_URL ? [process.env.SITE_URL] : []),
    ],
    methods: ["GET", "POST", "OPTIONS"],
    credentials: true,
    exposedHeaders: ["x-trace-id"],
  },
  transportEntries: {
    "*.http": {
      options: {
        subscriptions: {
          kind: "ws",
          location: "/graphql",
          options: {
            connectionParams: {
              cookie: "{context.headers.cookie}",
              origin: "{context.headers.origin}",
            },
          },
        },
      },
    },
  },
});
