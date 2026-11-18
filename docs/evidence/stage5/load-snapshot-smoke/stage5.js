import http from "k6/http";
import { check, sleep } from "k6";
import exec from "k6/execution";
import { Counter, Rate, Trend } from "k6/metrics";
import { SharedArray } from "k6/data";

const cohort = new SharedArray("real-cohort", () => JSON.parse(open("/data/cohort.json")));

const env = __ENV;
const mode = env.MODE || "baseline";
const failures = new Rate("operation_errors");
const latency = new Trend("operation_duration", true);
const operations = new Counter("operation_count");
const coldFirst = new Trend("cold_first_operation", true);
const durations = { warm: "2m", baseline: "10m", contention: "1m", pilot: "1m", smoke: "10s" };
const thresholds = {
  operation_errors: [{ threshold: "rate<0.10", abortOnFail: true, delayAbortEval: "30s" }],
};
for (const operation of ["catalog", "detail", "search", "private"]) {
  thresholds[`operation_duration{operation:${operation}}`] = ["p(95)>=0"];
  thresholds[`operation_errors{operation:${operation}}`] = ["rate<=1"];
  thresholds[`operation_count{operation:${operation}}`] = ["count>0"];
}
if (mode === "stress") {
  for (const load of ["20", "50", "100"]) {
    thresholds[`operation_duration{load:${load}}`] = ["p(95)>=0"];
    thresholds[`operation_count{load:${load}}`] = ["count>0"];
    thresholds[`operation_errors{load:${load}}`] = [
      {
        threshold: "rate<0.10",
        abortOnFail: true,
        delayAbortEval: { 20: "30s", 50: "3m30s", 100: "6m30s" }[load],
      },
    ];
  }
}
if (mode === "baseline" || mode === "pilot") {
  thresholds.operation_errors.push({ threshold: "rate<0.01" });
  thresholds["operation_duration{operation:catalog}"] = ["p(95)<500"];
  thresholds["operation_duration{operation:detail}"] = ["p(95)<1000"];
  thresholds["operation_duration{operation:search}"] = ["p(95)<1000"];
}
export const options = {
  scenarios: {
    mixed:
      mode === "stress"
        ? {
            executor: "ramping-vus",
            startVUs: 20,
            stages: [
              { target: 20, duration: "3m" },
              { target: 50, duration: "0s" },
              { target: 50, duration: "3m" },
              { target: 100, duration: "0s" },
              { target: 100, duration: "3m" },
            ],
            gracefulRampDown: "10s",
          }
        : mode === "cold" || mode === "smoke"
          ? {
              executor: "shared-iterations",
              vus: mode === "cold" ? 1 : 2,
              iterations: 20,
              maxDuration: "2m",
            }
          : {
              executor: "constant-vus",
              vus: mode === "smoke" ? 2 : 20,
              duration: durations[mode],
              gracefulStop: "10s",
            },
  },
  thresholds,
  summaryTrendStats: ["avg", "min", "med", "max", "p(90)", "p(95)", "p(99)"],
};

const catalog = `query LoadCatalog($after:String,$sort:PackageSort!) {
  packages(first:20,after:$after,sort:$sort,filter:{source:"PYPI"}) {
    nodes { id name summary license requiresPython starProjection { stars status }
      releases(first:1,source:"PYPI") { nodes { version } } }
    pageInfo { hasNextPage endCursor }
  }
}`;
const detail = `query LoadDetail($id:ID!) { package(id:$id) {
  id name summary license requiresPython pypiFreshness { status checkedAt }
  repositories(first:5) { nodes { status repository { fullName stars url } } }
  releases(first:5,source:"PYPI") { nodes { version yanked
    dependencies(first:20) { nodes { name specifier marker extras } }
    scan { status checkedAt findings(first:20) { nodes { id summary } } }
  } }
} }`;
const search = `query LoadSearch($term:String!) {
  packages(first:20,search:$term,filter:{source:"PYPI"}) {
    nodes { id name summary } pageInfo { hasNextPage endCursor }
  }
}`;
const privateQuery = `query LoadWorkspace { myCollections(first:5) {
  nodes { id name } pageInfo { hasNextPage }
} myNotifications(first:5) { nodes { id message readAt } } }`;

function request(query, variables, operation, token) {
  const load =
    mode === "stress"
      ? String(
          [20, 50, 100][Math.min(2, Math.floor(exec.instance.currentTestRunDuration / 180000))],
        )
      : mode;
  const tags = { operation, load };
  const response = http.post(
    env.GRAPHQL_URL || "http://gateway:4000/graphql",
    JSON.stringify({ query, variables }),
    {
      headers: {
        "content-type": "application/json",
        ...(token ? { "x-workspace-token": token } : {}),
      },
      tags,
      timeout: "10s",
    },
  );
  let body;
  try {
    body = response.json();
  } catch {
    body = null;
  }
  const valid = response.status === 200 && body && body.data && !body.errors;
  if (operation !== "setup") {
    failures.add(!valid, tags);
    latency.add(response.timings.duration, tags);
    operations.add(1, tags);
    if (mode === "cold" && exec.scenario.iterationInTest === 0) {
      coldFirst.add(response.timings.duration);
    }
    check(response, { "HTTP and GraphQL succeed": () => Boolean(valid) });
  }
  return valid ? body.data : null;
}

export function setup() {
  // A reproducible, saved read-only sample. No load operation starts imports.
  const ids = cohort.map((row) => row.package_id);
  const names = cohort.map((row) => row.name);
  const cursors = [null];
  let after = null;
  for (let page = 0; mode !== "cold" && page < 10; page++) {
    const data = request(catalog, { after, sort: "NAME_ASC" }, "setup");
    if (!data || !data.packages.nodes.length) throw new Error("Real PyPI catalog unavailable");
    if (!data.packages.pageInfo.hasNextPage) break;
    after = data.packages.pageInfo.endCursor;
    cursors.push(after);
  }
  if (!env.WORKSPACE_A || !env.WORKSPACE_B) throw new Error("Workspace test credentials missing");
  if (!ids.length) throw new Error("Saved real cohort missing");
  return { ids, names, cursors };
}

export default function mixedOperation(data) {
  const n = exec.scenario.iterationInTest;
  const slot = n % 20;
  const sample = (n * 37) % data.ids.length;
  if (slot < 12) {
    // NAME cursor pages; other sort orders start at their own first page.
    const sort = ["NAME_ASC", "UPDATED_DESC", "STARS_DESC"][n % 3];
    request(
      catalog,
      { sort, after: sort === "NAME_ASC" ? data.cursors[n % data.cursors.length] : null },
      "catalog",
    );
  } else if (slot < 17) {
    request(detail, { id: data.ids[sample] }, "detail");
  } else if (slot < 19) {
    request(search, { term: n % 2 ? data.names[sample] : "python" }, "search");
  } else {
    request(
      privateQuery,
      {},
      "private",
      Math.floor(n / 20) % 2 ? env.WORKSPACE_A : env.WORKSPACE_B,
    );
  }
  sleep(1);
}

export function handleSummary(data) {
  return { ["/results/" + mode + ".json"]: JSON.stringify({ mode, ...data }, null, 2) + "\n" };
}
