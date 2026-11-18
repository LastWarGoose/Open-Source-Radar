import "server-only";
import { tracedFetch } from "./traced-fetch";
import { HttpLink } from "@apollo/client";
import {
  ApolloClient,
  InMemoryCache,
  registerApolloClient,
} from "@apollo/client-integration-nextjs";

export const { getClient } = registerApolloClient(
  () =>
    new ApolloClient({
      cache: new InMemoryCache(),
      link: new HttpLink({
        fetch: tracedFetch,
        uri: process.env.GRAPHQL_URL ?? "http://localhost:4000/graphql",
        fetchOptions: { cache: "no-store" },
      }),
    }),
);
