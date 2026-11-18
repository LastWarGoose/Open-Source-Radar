import { composeServices } from "@apollo/composition";
import { parse } from "graphql";
import { readFile, writeFile } from "node:fs/promises";

const names = ["catalog", "repositories", "security", "workspace"];
const services = await Promise.all(
  names.map(async (name) => ({
    name,
    url: process.env[`${name.toUpperCase()}_URL`] ?? `http://${name}:8000/graphql`,
    typeDefs: parse(
      await readFile(new URL(`../packages/graphql/${name}.graphql`, import.meta.url), "utf8"),
    ),
  })),
);
const result = composeServices(services);
if (result.errors) {
  for (const error of result.errors) console.error(error.message);
  process.exit(1);
}
await writeFile(
  new URL("../packages/graphql/supergraph.graphql", import.meta.url),
  result.supergraphSdl + "\n",
);
console.log("Composed Catalog + Repositories + Security + Workspace (Federation 2)");
