"""Paired full-data read load while a bounded 100-package refresh runs in the background."""

import argparse
import hashlib
import json
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import httpx
from dotenv import dotenv_values

from scripts.measure_stage5 import CONSUMERS, OUTPUT, ROOT, checks, compose
from scripts.report_stage5 import read
from scripts.run_stage5 import STATUS


def select_targets(campaign: str) -> None:
    # Administrative read within Catalog only. No code or files from packages are fetched.
    names = [
        row["name"]
        for row in read(
            "catalog",
            """
        SELECT payload->>'name' AS name FROM source_work
        WHERE parent_id=:campaign AND status='succeeded'
          AND jsonb_array_length(checkpoint->'urls')=0
        ORDER BY payload->>'name' LIMIT 100""",
            {"campaign": UUID(campaign)},
        )
    ]
    assert len(names) == 100
    manifest = {
        "names": names,
        "target": 100,
        "seed": "stage5-contention-v1",
        "index_sha256": hashlib.sha256(json.dumps(names).encode()).hexdigest(),
        "policy": "First 100 already imported names with no declared project URLs; "
        "bounded refresh of existing data, no new cohort names",
    }
    Path("/evidence/contention-selection.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("campaign")
    parser.add_argument("--select", action="store_true")
    args = parser.parse_args()
    if args.select:
        select_targets(args.campaign)
        return
    baseline = OUTPUT / "load-final/baseline.json"
    assert baseline.exists(), "Complete isolated baseline first"
    target = OUTPUT / "load-contention-full"
    if target.exists():
        raise SystemExit("Contention run already exists")
    checks("scripts.contention_stage5", args.campaign, "--select")
    progress = OUTPUT / "contention-progress.json"
    secret = dotenv_values(ROOT / ".env").get("DEV_ADMIN_TOKEN")
    assert secret

    def status(identity: str) -> dict:
        response = httpx.post(
            "http://127.0.0.1:4000/graphql",
            timeout=30,
            headers={"x-dev-admin-token": secret},
            json={"query": STATUS, "variables": {"id": identity}},
        )
        response.raise_for_status()
        body = response.json()
        assert not body.get("errors")
        return {
            "checked_at": datetime.now(UTC).isoformat(),
            "campaign": body["data"]["importCampaign"],
        }

    codes = {}
    try:
        compose("stop", *CONSUMERS)
        subprocess.run(
            [
                sys.executable,
                "-m",
                "scripts.run_stage5",
                "--start-only",
                "--manifest",
                str(OUTPUT / "contention-selection.json"),
                "--output",
                str(progress),
            ],
            cwd=ROOT,
            check=True,
        )
        identity = json.loads(progress.read_text(encoding="utf-8"))["campaign"]["id"]
        compose("up", "-d", "--no-deps", "--wait", *CONSUMERS, bulk=True)
        before = status(identity)
        assert before["campaign"]["pending"] > 0, "Refresh finished before load began"
        result = subprocess.run(
            [sys.executable, "-m", "scripts.load_stage5", "contention", "--output", str(target)],
            cwd=ROOT,
            check=False,
        )
        codes["load"] = result.returncode
        after = status(identity)
        (target / "refresh-overlap.json").write_text(
            json.dumps({"before": before, "after": after}, indent=2) + "\n", encoding="utf-8"
        )
        assert after["campaign"]["succeeded"] > before["campaign"]["succeeded"]
        subprocess.run(
            [
                sys.executable,
                "-m",
                "scripts.run_stage5",
                "--manifest",
                str(OUTPUT / "contention-selection.json"),
                "--output",
                str(progress),
            ],
            cwd=ROOT,
            check=True,
        )
        # Wait for the actual source jobs, not only cross-service enqueue acknowledgements.
        assert status(identity)["campaign"]["succeeded"] == 100
        for _ in range(60):
            checks("scripts.report_stage5", identity, "--output", "/evidence/contention-refresh")
            report = json.loads((OUTPUT / "contention-refresh/source-report.json").read_text())
            if not any(
                report[source]["cohort_jobs"].get("queued", 0) for source in ("osv", "github")
            ):
                assert report["osv"]["cohort_statuses"].get("SUCCESS") == 100
                break
            time.sleep(10)
        else:
            raise RuntimeError("Enrichment has not finished; retain progress and investigate")
    finally:
        compose("up", "-d", "--no-deps", "--wait", *CONSUMERS)
    print("PASS: full-data contention run and bounded refresh completed; default budgets restored")
    if any(codes.values()):
        raise SystemExit("Contention error safeguard was exceeded; inspect evidence")


if __name__ == "__main__":
    main()
