import { createHash } from "node:crypto";
import { createServer } from "node:http";
import { performance } from "node:perf_hooks";
import { GraphQLError, getNamedType, getOperationAST, valueFromASTUntyped } from "graphql";
import { Counter, Gauge, Histogram, Registry } from "prom-client";
import { context, propagation, trace, ROOT_CONTEXT } from "@graphql-hive/gateway/opentelemetry/api";
import { openTelemetrySetup } from "@graphql-hive/gateway/opentelemetry/setup";
import { OTLPTraceExporter } from "@opentelemetry/exporter-trace-otlp-http";

const endpoint = process.env.OTEL_EXPORTER_OTLP_ENDPOINT;
if (endpoint)
  openTelemetrySetup({
    resource: { serviceName: "gateway" },
    samplingRate: 0.1,
    contextManager: null,
    traces: { exporter: new OTLPTraceExporter({ url: endpoint + "/v1/traces" }) },
  });

const registry = new Registry();
const base = { registers: [registry] };
const duration = new Histogram({
  ...base,
  name: "radar_graphql_seconds",
  help: "GraphQL execution latency",
  labelNames: ["operation"],
  buckets: [0.025, 0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10],
});
const errors = new Counter({
  ...base,
  name: "radar_graphql_errors_total",
  help: "Results with GraphQL errors",
  labelNames: ["operation"],
});
const denied = new Counter({
  ...base,
  name: "radar_graphql_rejected_total",
  help: "Gateway admission decisions",
  labelNames: ["reason"],
});
const active = new Gauge({
  ...base,
  name: "radar_subscriptions",
  help: "Active gateway subscriptions",
});
if (endpoint)
  createServer(async (req, res) => {
    if (req.url !== "/metrics") {
      res.writeHead(404).end();
      return;
    }
    res.setHeader("Content-Type", registry.contentType);
    res.end(await registry.metrics());
  })
    .listen(9464, "0.0.0.0")
    .unref();

const names = new Set(
  "PublicCatalog CatalogLicenses PublicPackage PackageMetadata ComparePackages Session Collections CollectionItems Follows Notifications AdminJobs AdminJob ImportProgress Login Register Logout RecoverAccount StartImport ResumeImport CreateCollection DeleteCollection AddToCollection RemoveFromCollection FollowPackage UnfollowPackage ReadNotification LoadCatalog LoadDetail LoadSearch LoadWorkspace".split(
    " ",
  ),
);
const carriers = new WeakMap();
const metered = new WeakSet();
const countedErrors = new WeakSet();
export const outbound = (request) => carriers.get(request) ?? {};
const ongoing = new Map();
let total = 0;
const buckets = new Map();
const clearExpired = setInterval(() => {
  for (const [key, bucket] of buckets) if (bucket.until <= Date.now()) buckets.delete(key);
}, 60000);
clearExpired.unref();
function allowed(key, max, ms) {
  let bucket = buckets.get(key);
  if (!bucket || bucket.until <= Date.now()) {
    if (!bucket && buckets.size >= 8192) return false;
    bucket = { count: 0, until: Date.now() + ms };
    buckets.set(key, bucket);
  }
  return ++bucket.count <= max;
}

function rateLimit(request, peer) {
  const cookie = request?.headers
    .get("cookie")
    ?.match(/(?:^|;\s*)radar_session=([^;]{1,128})(?:;|$)/)?.[1];
  if (!allowed("global", 200, 1000) || !allowed("ip:" + peer, 100, 1000)) return "RATE_LIMIT";
  if (cookie && !allowed("session:" + createHash("sha256").update(cookie).digest("hex"), 40, 1000))
    return "RATE_LIMIT";
}

function refuse(code) {
  denied.inc({ reason: code });
  return { errors: [new GraphQLError("Operation limit reached", { extensions: { code } })] };
}

// Count list fan-out through fragments, aliases, directives and variable page sizes.
export function admission(args, operation, maxCost = 100000) {
  const variables = Object.fromEntries(
    (operation.variableDefinitions ?? [])
      .filter((v) => v.defaultValue)
      .map((v) => [v.variable.name.value, valueFromASTUntyped(v.defaultValue)]),
  );
  Object.assign(variables, args.variableValues);
  const fragments = new Map(
    args.document.definitions
      .filter((d) => d.kind === "FragmentDefinition")
      .map((f) => [f.name.value, f]),
  );
  let cost = 0,
    aliases = 0,
    visits = 0,
    administrative = false;
  function walk(set, parent, factor, depth) {
    if (depth > 16 || ++visits > 5000) return "DEPTH_LIMIT";
    for (const field of set.selections) {
      if (
        field.directives?.some((d) => {
          const arg = d.arguments?.find((a) => a.name.value === "if");
          if (!arg) return false;
          const value = valueFromASTUntyped(arg.value, variables);
          return (
            (d.name.value === "skip" && value === true) ||
            (d.name.value === "include" && value === false)
          );
        })
      )
        continue;
      if (field.kind !== "Field") {
        const fragment = field.kind === "FragmentSpread" ? fragments.get(field.name.value) : field;
        if (!fragment) continue;
        const reason = walk(
          fragment.selectionSet,
          fragment.typeCondition ? args.schema.getType(fragment.typeCondition.name.value) : parent,
          factor,
          depth,
        );
        if (reason) return reason;
        continue;
      }
      if (field.alias && ++aliases > 32) return "ALIAS_LIMIT";
      const name = field.name.value;
      if (
        operation.operation === "mutation" &&
        [
          "requestImport",
          "resumeImport",
          "requestCampaign",
          "requestProbeJob",
          "requestRepositoryImport",
          "requestSecurityImport",
        ].includes(name)
      )
        administrative = true;
      if ((cost += factor) > maxCost) return "COST_LIMIT";
      if (!field.selectionSet) continue;
      const def = parent?.getFields?.()[name];
      const page = def?.args.find((a) => a.name === "first");
      const arg = field.arguments?.find((a) => a.name.value === "first");
      const size = arg ? valueFromASTUntyped(arg.value, variables) : page?.defaultValue;
      const reason = walk(
        field.selectionSet,
        def ? getNamedType(def.type) : undefined,
        factor * (page ? Math.max(1, Math.min(101, Number(size) || 20)) : 1),
        depth + 1,
      );
      if (reason) return reason;
    }
  }
  const root = args.schema.getRootType(operation.operation);
  return { reason: walk(operation.selectionSet, root, 1, 0), administrative };
}

function begin({ args, setResultAndStopExecution }, subscription) {
  const op = getOperationAST(args.document, args.operationName);
  if (!op) return;
  const ctx = args.contextValue;
  const request = ctx.request;
  const peer = ctx.req?.socket?.remoteAddress ?? "local";
  const raw = op.name?.value;
  const operation = names.has(raw) ? raw : "other";
  const { reason, administrative } = admission(args, op);
  const rejection =
    reason ||
    (!metered.has(request) && rateLimit(request, peer)) ||
    (administrative && !allowed("admin:" + peer, 30, 60000) ? "ADMIN_RATE_LIMIT" : undefined) ||
    (subscription && (total >= 128 || (ongoing.get(peer) ?? 0) >= 32)
      ? "SUBSCRIPTION_LIMIT"
      : undefined);
  if (rejection) {
    setResultAndStopExecution(refuse(rejection));
    return;
  }
  const started = performance.now();
  const parent = propagation.extract(ROOT_CONTEXT, {
    traceparent: request?.headers.get("traceparent") ?? "",
  });
  const span = trace
    .getTracer("radar")
    .startSpan("graphql." + op.operation, { attributes: { "radar.operation": operation } }, parent);
  const carrier = {};
  propagation.inject(trace.setSpan(context.active(), span), carrier);
  if (request) carriers.set(request, carrier);
  if (subscription) {
    total++;
    ongoing.set(peer, (ongoing.get(peer) ?? 0) + 1);
    active.inc();
  }
  let finished = false;
  function finish() {
    if (finished) return;
    finished = true;
    duration.observe({ operation }, (performance.now() - started) / 1000);
    span.end();
    if (subscription) {
      total--;
      const count = ongoing.get(peer) - 1;
      if (count) ongoing.set(peer, count);
      else ongoing.delete(peer);
      active.dec();
    }
  }
  function inspect(result) {
    if (result?.errors?.length) {
      errors.inc({ operation });
      if (request) countedErrors.add(request);
      span.setStatus({ code: 2 });
    }
  }
  function done({ result }) {
    if (result && Symbol.asyncIterator in result)
      return { onNext: ({ result }) => inspect(result), onEnd: finish };
    inspect(result);
    finish();
  }
  return subscription
    ? { onSubscribeResult: done, onSubscribeError: finish }
    : { onExecuteDone: done };
}

export const controls = {
  onParams({ request, params, context, setResult }) {
    const reason = rateLimit(request, context.req?.socket?.remoteAddress ?? "local");
    metered.add(request);
    if (reason) return setResult(refuse(reason));
    if (Buffer.byteLength(JSON.stringify(params.variables ?? {})) > 4 * 1024 * 1024)
      setResult(refuse("VARIABLE_LIMIT"));
  },
  onResultProcess({ request, result }) {
    if (result?.errors?.length && !countedErrors.has(request)) errors.inc({ operation: "other" });
  },
  onExecute: (payload) => begin(payload, false),
  onSubscribe: (payload) => begin(payload, true),
  onResponse({ request, response }) {
    const header = outbound(request).traceparent;
    if (header) response.headers.set("x-trace-id", header.split("-")[1]);
  },
};
