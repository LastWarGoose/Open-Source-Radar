import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { test } from "node:test";
import { buildSchema, getIntrospectionQuery, parse } from "graphql";
import { admission, controls } from "../../gateway/controls.mjs";

const schema = buildSchema(readFileSync("packages/graphql/supergraph.graphql", "utf8"));
test("a cancelled subscription releases its gateway slot", () => {
  const document = parse('subscription Updated{packageUpdated(id:"pypi:fastapi"){id}}');
  const request = new Request("http://localhost/graphql");
  const args = {
    schema,
    document,
    contextValue: { request, req: { socket: { remoteAddress: "unit-subscriptions" } } },
  };
  let rejection;
  function open() {
    return controls.onSubscribe({
      args,
      setResultAndStopExecution(result) {
        rejection = result.errors[0].extensions.code;
      },
    });
  }
  const streams = [];
  const result = {
    async *[Symbol.asyncIterator]() {
      yield { data: {} };
    },
  };
  for (let i = 0; i < 32; i++) streams.push(open().onSubscribeResult({ result }));
  assert.equal(open(), undefined);
  assert.equal(rejection, "SUBSCRIPTION_LIMIT");
  streams.pop().onEnd();
  const next = open();
  assert.ok(next);
  next.onSubscribeResult({ result }).onEnd();
  for (const stream of streams) stream.onEnd();
});

test("session rate budget applies across successive HTTP operations", () => {
  const request = new Request("http://localhost/graphql", {
    headers: { cookie: "radar_session=local-unit-fixture" },
  });
  let rejected = 0;
  for (let i = 0; i < 41; i++)
    controls.onParams({
      request,
      params: {},
      context: {},
      setResult(result) {
        assert.equal(result.errors[0].extensions.code, "RATE_LIMIT");
        rejected++;
      },
    });
  assert.equal(rejected, 1);
});
test("the same catalog operation consumes a larger budget when its page grows", () => {
  const document = parse("query Catalog($size:Int!){packages(first:$size){nodes{name}}}");
  const [operation] = document.definitions;
  const evaluate = (size) =>
    admission({ schema, document, variableValues: { size } }, operation, 10).reason;
  assert.equal(evaluate(2), undefined);
  assert.equal(evaluate(8), "COST_LIMIT");
});
test("gateway budgets admit introspection, 48 catalog rows and all four comparison slots", () => {
  const webRequire = createRequire(new URL("../../apps/web/package.json", import.meta.url));
  const { addTypenameToDocument } = webRequire("@apollo/client/utilities");
  const sources = [
    parse(getIntrospectionQuery()),
    ...["public", "personal", "operations"].map((name) =>
      addTypenameToDocument(parse(readFileSync(`apps/web/src/${name}.graphql`, "utf8"))),
    ),
  ];
  for (const document of sources) {
    for (const op of document.definitions.filter((def) => def.kind === "OperationDefinition")) {
      for (const hasVersion of [false, true]) {
        const vars = { first: 48, hasVersion, hasB: true, hasC: true, hasD: true };
        assert.equal(
          admission({ schema, document, variableValues: vars }, op).reason,
          undefined,
          op.name?.value,
        );
      }
    }
  }
});
