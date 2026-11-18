"""Bounded manual live import. Credentials are read locally and never printed."""

import argparse
import json
import time
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4, uuid5

import httpx
from dotenv import dotenv_values

TARGETS: list[dict[str, str | None]] = [
    {"name": "fastapi", "version": None},
    {"name": "requests", "version": "2.31.0"},
]
START = """mutation Start($key: UUID!, $targets: [ImportTarget!]!) {
  requestImport(requestKey: $key, targets: $targets) { id status processed }
}"""
JOB = """query Job($id: UUID!) { importJob(id: $id) { id status processed errorCode } }"""
ENRICH = """query Enrichment($repository: UUID!, $security: UUID!) {
  repositoryImportJob(id: $repository) { status errorCode attempts }
  securityImportJob(id: $security) { status errorCode attempts }
}"""
CATALOG = """query Evidence($name: String!) {
  packages(first: 20, search: $name) { nodes {
    id name source fetchedAt pypiFreshness { status checkedAt lastSuccessAt }
    githubFreshness { status checkedAt lastSuccessAt errorCode }
    repositories(first: 10) { nodes { status repository { id fullName source stars fetchedAt } } }
    releases(first: 100) { nodes { id version source
      scan { status source checkedAt lastSuccessAt errorCode
        findings(first: 100) { nodes { id summary source aliases(first: 100) { nodes { name } } } }
      }
    } }
  } }
}"""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="docs/evidence/stage3-live.json")
    args = parser.parse_args()
    token = dotenv_values(".env").get("DEV_ADMIN_TOKEN")
    if not token:
        raise SystemExit("Run bootstrap first")
    with httpx.Client(
        base_url="http://localhost:4000", timeout=20, headers={"x-dev-admin-token": token}
    ) as client:

        def gql(query: str, variables: dict) -> dict:
            response = client.post("/graphql", json={"query": query, "variables": variables})
            response.raise_for_status()
            result = response.json()
            if result.get("errors"):
                raise RuntimeError("GraphQL rejected live import")
            return result["data"]

        reports = []
        snapshots = []
        for attempt in range(2):
            key = str(uuid4())
            job = gql(START, {"key": key, "targets": TARGETS})["requestImport"]
            assert gql(START, {"key": key, "targets": TARGETS})["requestImport"]["id"] == job["id"]
            print("Live run", attempt + 1, "queued", flush=True)
            deadline = time.monotonic() + 300
            enriched = []
            while time.monotonic() < deadline:
                job = gql(JOB, {"id": job["id"]})["importJob"]
                if job["status"] == "failed":
                    raise RuntimeError("PyPI import failed: " + str(job["errorCode"]))
                enriched = [
                    gql(
                        ENRICH,
                        {
                            "repository": str(uuid5(uuid5(UUID(job["id"]), str(i)), "github")),
                            "security": str(uuid5(uuid5(UUID(job["id"]), str(i)), "osv")),
                        },
                    )
                    for i in range(len(TARGETS))
                ]
                statuses = [value for row in enriched for value in row.values()]
                failed = [value for value in statuses if value and value["status"] == "failed"]
                if failed:
                    raise RuntimeError("Enrichment failed: " + str(failed))
                if job["status"] == "succeeded" and all(
                    value and value["status"] == "succeeded" for value in statuses
                ):
                    break
                time.sleep(3)
            else:
                raise RuntimeError("Live import deadline reached; progress retained in PostgreSQL")
            snapshot = []
            for target in TARGETS:
                rows = gql(CATALOG, {"name": target["name"]})["packages"]["nodes"]
                snapshot.append(next(row for row in rows if row["name"] == target["name"]))
            reports.append({"job": job, "enrichment": enriched})
            snapshots.append(snapshot)
            print("Live run", attempt + 1, "completed across all three sources", flush=True)

        def identities(snapshot: list[dict]) -> dict:
            return {
                row["id"]: {
                    "releases": sorted(r["id"] for r in row["releases"]["nodes"]),
                    "repositories": sorted(
                        r["repository"]["id"] for r in row["repositories"]["nodes"]
                    ),
                    "findings": sorted(
                        (r["id"], f["id"])
                        for r in row["releases"]["nodes"]
                        if r["scan"]
                        for f in r["scan"]["findings"]["nodes"]
                    ),
                }
                for row in snapshot
            }

        assert identities(snapshots[0]) == identities(snapshots[1]), (
            "Repeated import changed identities"
        )
        requests = next(row for row in snapshots[-1] if row["name"] == "requests")
        historical = next(r for r in requests["releases"]["nodes"] if r["version"] == "2.31.0")
        assert historical["scan"]["status"] == "SUCCESS"
        assert historical["scan"]["findings"]["nodes"], "Real OSV finding required"
        output = {
            "checked_at": datetime.now(UTC).isoformat(),
            "targets": TARGETS,
            "historical_version": "requests 2.31.0 is a demonstration, not a recommendation",
            "runs": reports,
            "stable_identities": True,
            "packages": snapshots[-1],
        }
        Path(args.output).write_text(
            json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print("PASS: live PyPI/GitHub/OSV, historical advisory, stable repeated import", flush=True)


if __name__ == "__main__":
    main()
