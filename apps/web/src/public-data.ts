import "server-only";
import { cache } from "react";
import { CombinedGraphQLErrors } from "@apollo/client/errors";
import { getClient } from "./apollo-server";
import {
  CatalogLicensesDocument,
  NearestOsvScanDocument,
  NearestPypiReleaseDocument,
  PackageMetadataDocument,
  PublicPackageDocument,
} from "./gql/graphql";
import type { CatalogLicensesQuery, ScanSummaryFragment } from "./gql/graphql";

async function loadLicensePage(
  after: string | null,
): Promise<CatalogLicensesQuery["catalogLicenses"] | undefined> {
  const result = await getClient().query({
    query: CatalogLicensesDocument,
    variables: { after },
    errorPolicy: "all",
  });
  return result.error ? undefined : result.data?.catalogLicenses;
}

async function readCatalogLicenses() {
  const licenses: string[] = [];
  let after: string | null = null;
  do {
    const page = await loadLicensePage(after);
    if (!page) return null;
    licenses.push(...page.nodes);
    after = page.pageInfo.hasNextPage ? (page.pageInfo.endCursor ?? null) : null;
  } while (after);
  return licenses;
}

// Only this public dictionary is shared across requests. A committed license change
// supplies a new revision, including when an import removes the last use of a license.
let licenseCache: { revision: string; pending: Promise<string[] | null> } | undefined;

export function loadCatalogLicenses(revision: string | null | undefined) {
  if (!revision) return readCatalogLicenses();
  if (licenseCache?.revision === revision) return licenseCache.pending;
  const pending = readCatalogLicenses();
  licenseCache = { revision, pending };
  const discard = () => {
    if (licenseCache?.pending === pending) licenseCache = undefined;
  };
  void pending.then((values) => {
    if (!values) discard();
  }, discard);
  return pending;
}

export const loadPackageMetadata = (name: string) =>
  getClient().query({
    query: PackageMetadataDocument,
    variables: { id: "pypi:" + name },
    errorPolicy: "all",
  });

export function hasOsvResult(scan?: ScanSummaryFragment | null) {
  return scan?.source === "OSV" && Boolean(scan.lastSuccessAt);
}

export const loadNearestScan = cache(async (id: string, version: string) => {
  const result = await getClient().query({
    query: NearestOsvScanDocument,
    variables: { id, version },
    errorPolicy: "all",
  });
  return { scan: result.data?.package?.nearestOsvScan, unavailable: Boolean(result.error) };
});
export const loadNearestRelease = cache(async (id: string, version: string) =>
  getClient().query({
    query: NearestPypiReleaseDocument,
    variables: { id, version, dependencyAfter: null },
    errorPolicy: "all",
  }),
);

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
export function failedField(error: unknown, field: string, alias?: string) {
  return (
    CombinedGraphQLErrors.is(error) &&
    error.errors.some(
      ({ path }) => path?.includes(field) && (alias === undefined || path[0] === alias),
    )
  );
}
export function badInput(error: unknown) {
  return (
    CombinedGraphQLErrors.is(error) &&
    error.errors.some((item) => item.extensions?.code === "BAD_USER_INPUT")
  );
}
