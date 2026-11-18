import type { PackageSort } from "./gql/graphql";

export type Search = Record<string, string | string[] | undefined>;
export const one = (value: string | string[] | undefined) =>
  typeof value === "string" ? value : "";
export const validName = (value: string) =>
  /^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(value) && value.length <= 200;
export const compareURL = (names: string[], differences = false) =>
  "/compare" +
  (names.length ? "?packages=" + names.join(",") : "") +
  (differences && names.length > 1 ? "&differences=1" : "");
export function catalogState(search: Search) {
  const sorts: PackageSort[] = ["RELEVANCE", "NAME_ASC", "UPDATED_DESC", "STARS_DESC"];
  // Previous catalog links omitted NAME_ASC when encoding their cursor.
  const fallback: PackageSort = one(search.after) || search.back ? "NAME_ASC" : "RELEVANCE";
  const sort = sorts.find((value) => value === one(search.sort)) ?? fallback;
  const size = [1, 12, 24, 48].includes(Number(one(search.size))) ? Number(one(search.size)) : 12;
  const trail = (Array.isArray(search.back) ? search.back : search.back ? [search.back] : [])
    .filter((value) => value.length <= 2048)
    .slice(-20);
  return {
    q: one(search.q).slice(0, 200),
    license: one(search.license).slice(0, 200),
    releases: ["yes", "no"].includes(one(search.releases)) ? one(search.releases) : "",
    sort,
    size,
    after: one(search.after).slice(0, 2048),
    trail,
  };
}
export function catalogURL(
  state: ReturnType<typeof catalogState>,
  after = "",
  trail: string[] = [],
) {
  const p = new URLSearchParams();
  if (state.q) p.set("q", state.q);
  if (state.license) p.set("license", state.license);
  if (state.releases) p.set("releases", state.releases);
  if (state.sort !== "RELEVANCE" || after || trail.length) p.set("sort", state.sort);
  if (state.size !== 12) p.set("size", String(state.size));
  if (after) p.set("after", after);
  for (const previous of trail.slice(-20)) if (previous) p.append("back", previous);
  return p.size ? "/?" + p.toString() : "/#catalog";
}
export function packageURL(name: string, values: Record<string, string | undefined> = {}) {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(values)) if (value) params.set(key, value);
  return "/packages/" + encodeURIComponent(name) + (params.size ? "?" + params : "");
}

export function catalogReturn(value: Search[string]) {
  const path = one(value);
  if (!path.startsWith("/?")) return "/#catalog";
  const params = new URLSearchParams(path.slice(2));
  const search: Search = Object.fromEntries(params);
  if (params.has("back")) search.back = params.getAll("back");
  const state = catalogState(search);
  return catalogURL(state, state.after, state.trail);
}
