import assert from "node:assert/strict";
import { test } from "node:test";
import { createClient } from "graphql-ws";

const endpoint = process.env.GRAPHQL_URL ?? "http://localhost:4000/graphql";
const id = "pypi:fastapi";
const fields = "id name demoRevision repository { fullName stars }";

async function graphql(query, variables = { id }) {
  const response = await fetch(endpoint, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ query, variables }),
    signal: AbortSignal.timeout(10_000),
  });
  assert.equal(response.status, 200);
  return response.json();
}

test("query and mutation resolve fields from both subgraphs; unknown ID is null", async () => {
  const before = await graphql(
    `query Package($id: ID!) { package: demoPackage(id: $id) { ${fields} } }`,
  );
  assert.equal(before.errors, undefined);
  assert.equal(before.data.package.name, "fastapi");
  assert.equal(before.data.package.repository.fullName, "fastapi/fastapi");
  const after = await graphql(`mutation Advance($id: ID!) { advanceDemo(id: $id) { ${fields} } }`);
  assert.equal(after.errors, undefined);
  assert.equal(after.data.advanceDemo.demoRevision, before.data.package.demoRevision + 1);
  assert.equal(after.data.advanceDemo.repository.stars, 12345);
  const missing = await graphql(
    "query Missing($id: ID!) { package: demoPackage(id: $id) { id } }",
    {
      id: "missing",
    },
  );
  assert.equal(missing.errors, undefined);
  assert.equal(missing.data.package, null);
});

test(
  "federated subscription receives mutation and recovers state after socket termination",
  { timeout: 25_000 },
  async () => {
    const client = createClient({
      url: endpoint.replace(/^http/, "ws"),
      retryAttempts: 5,
      retryWait: async () => {},
    });
    const events = [];
    let failure;
    const unsubscribe = client.subscribe(
      {
        query: `subscription Updated($id: ID!) { packageUpdated(id: $id) { ${fields} } }`,
        variables: { id },
      },
      {
        next: (value) => events.push(value),
        error: (error) => {
          failure = error;
        },
        complete() {},
      },
    );
    async function waitFor(predicate) {
      const deadline = Date.now() + 10_000;
      while (!predicate()) {
        if (failure) throw failure;
        if (Date.now() > deadline) throw new Error("Timed out waiting for federated event");
        await new Promise((resolve) => setTimeout(resolve, 25));
      }
    }
    try {
      await waitFor(() => events.length > 0);
      assert.equal(events[0].errors, undefined);
      assert.equal(events[0].data.packageUpdated.repository.fullName, "fastapi/fastapi");
      const initial = events[0].data.packageUpdated.demoRevision;
      await graphql("mutation Advance($id: ID!) { advanceDemo(id: $id) { demoRevision } }");
      await waitFor(() =>
        events.some((event) => event.data?.packageUpdated.demoRevision === initial + 1),
      );
      const oldCount = events.length;
      client.terminate();
      await waitFor(() => events.length > oldCount);
      assert.equal(events.at(-1).errors, undefined);
      assert.equal(events.at(-1).data.packageUpdated.repository.fullName, "fastapi/fastapi");
      const state = await graphql(
        "query State($id: ID!) { package: demoPackage(id: $id) { demoRevision } }",
      );
      assert.equal(events.at(-1).data.packageUpdated.demoRevision, state.data.package.demoRevision);
    } finally {
      unsubscribe();
      await client.dispose();
    }
  },
);
