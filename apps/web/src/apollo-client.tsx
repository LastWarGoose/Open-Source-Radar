"use client";

import { HttpLink, split } from "@apollo/client";
import { GraphQLWsLink } from "@apollo/client/link/subscriptions";
import { getMainDefinition } from "@apollo/client/utilities";
import {
  ApolloClient,
  ApolloNextAppProvider,
  InMemoryCache,
} from "@apollo/client-integration-nextjs";
import { createClient } from "graphql-ws";
import { tracedFetch } from "./traced-fetch";
import type { ReactNode } from "react";

function makeClient() {
  const http = new HttpLink({
    fetch: tracedFetch,
    credentials: "include",
    uri:
      typeof window === "undefined"
        ? (process.env.GRAPHQL_URL ?? "http://localhost:4000/graphql")
        : (process.env.NEXT_PUBLIC_GRAPHQL_URL ?? "http://localhost:4000/graphql"),
  });
  const link =
    typeof window === "undefined"
      ? http
      : split(
          ({ query }) => {
            const definition = getMainDefinition(query);
            return (
              definition.kind === "OperationDefinition" && definition.operation === "subscription"
            );
          },
          new GraphQLWsLink(
            createClient({
              url: process.env.NEXT_PUBLIC_GRAPHQL_WS_URL ?? "ws://localhost:4000/graphql",
              retryAttempts: Infinity,
              connectionAckWaitTimeout: 10_000,
              keepAlive: 10_000,
              retryWait: async (retries) => {
                await new Promise((resolve) =>
                  setTimeout(resolve, Math.min(500 * 2 ** retries, 5_000)),
                );
              },
            }),
          ),
          http,
        );
  return new ApolloClient({ cache: new InMemoryCache(), link });
}

export function ApolloProvider({ children }: { children: ReactNode }) {
  return <ApolloNextAppProvider makeClient={makeClient}>{children}</ApolloNextAppProvider>;
}
