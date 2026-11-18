"""Start/resume a saved cohort through GraphQL; print only public progress and job IDs."""

import argparse
import json
import time
from datetime import UTC, datetime
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

import httpx
from dotenv import dotenv_values

FIELDS = """id status target succeeded failed pending candidatesConsumed candidatesTotal
manifestHash createdAt completedAt"""
START = (
    "mutation Start($key: UUID!, $names: [String!]!, $target: Int!) { "
    "requestCampaign(requestKey: $key, names: $names, target: $target) { " + FIELDS + " } }"
)
STATUS = "query Status($id: UUID!) { importCampaign(id: $id) { " + FIELDS + " } }"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", default="docs/evidence/stage5/selection.json")
    parser.add_argument("--output", default="docs/evidence/stage5/progress.json")
    parser.add_argument("--start-only", action="store_true")
    args = parser.parse_args()
    manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    key = str(
        uuid5(NAMESPACE_URL, "radar:stage5:" + manifest["index_sha256"] + ":" + manifest["seed"])
    )
    token = dotenv_values(".env").get("DEV_ADMIN_TOKEN")
    if not token:
        raise SystemExit("Local administrator credential is missing")
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with httpx.Client(
        base_url="http://localhost:4000", timeout=30, headers={"x-dev-admin-token": token}
    ) as client:

        def gql(query: str, variables: dict) -> dict:
            response = client.post("/graphql", json={"query": query, "variables": variables})
            response.raise_for_status()
            result = response.json()
            if result.get("errors"):
                raise RuntimeError("GraphQL rejected campaign operation; credentials omitted")
            return result["data"]

        campaign = gql(
            START, {"key": key, "names": manifest["names"], "target": manifest["target"]}
        )["requestCampaign"]
        while True:
            document = {
                "checked_at": datetime.now(UTC).isoformat(),
                "request_key": key,
                "campaign": campaign,
            }
            temporary = output.with_suffix(".tmp")
            temporary.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
            temporary.replace(output)
            print(
                f"{document['checked_at']} {campaign['id']}: {campaign['status']}; "
                f"{campaign['succeeded']}/{campaign['target']} succeeded; "
                f"{campaign['failed']} failed candidates; {campaign['pending']} pending",
                flush=True,
            )
            if args.start_only or campaign["status"] == "succeeded":
                return
            if campaign["status"] == "failed":
                raise SystemExit("Candidate list exhausted before target; see saved progress")
            time.sleep(30)
            campaign = gql(STATUS, {"id": campaign["id"]})["importCampaign"]


if __name__ == "__main__":
    main()
