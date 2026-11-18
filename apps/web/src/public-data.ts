import "server-only";
import { cache } from "react";
import { CombinedGraphQLErrors } from "@apollo/client/errors";
import { getClient } from "./apollo-server";
import { PublicPackageDocument } from "./gql/graphql";

export const loadPackage = cache(
  async (name: string, version = "", releaseAfter = "", dependencyAfter = "") =>
    getClient().query({
      query: PublicPackageDocument,
      variables: {
        id: "pypi:" + name,
        version,
        hasVersion: Boolean(version),
        releaseAfter: releaseAfter || null,
        dependencyAfter: dependencyAfter || null,
      },
      errorPolicy: "all",
    }),
);
export function failedField(error: unknown, field: string) {
  return CombinedGraphQLErrors.is(error) && error.errors.some((item) => item.path?.includes(field));
}
export function badInput(error: unknown) {
  return (
    CombinedGraphQLErrors.is(error) &&
    error.errors.some((item) => item.extensions?.code === "BAD_USER_INPUT")
  );
}
