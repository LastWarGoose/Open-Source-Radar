"""Local pinned k6 runner. Secrets are environment values, never CLI arguments/artifacts."""

import argparse
import hashlib
import json
import os
import subprocess
import threading
from datetime import UTC, datetime
from pathlib import Path

from dotenv import dotenv_values

from scripts.cohort_evidence import read_cohort, save_cohort
from scripts.windows_awake import prevent_idle_sleep
from services.workspace.access import DEV_ACTORS, dev_token

IMAGE = "grafana/k6:1.0.0@sha256:f21270290d702cbf0a7d6ba5d7ed100b63bcb233b558b885ed787547b3488279"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "mode", choices=["smoke", "contention", "pilot", "cold", "warm", "baseline", "stress"]
    )
    parser.add_argument("--output", default="docs/evidence/stage5/load")
    parser.add_argument("--monitor", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    output = (root / args.output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    evidence = root / "docs/evidence/stage5"
    raw_cohort = read_cohort(evidence).read_bytes()
    cohort_size = len(json.loads(raw_cohort))
    if args.mode in ("baseline", "warm", "cold", "stress") and cohort_size < 10000:
        raise SystemExit("Final measurements require at least 10000 imported cohort packages")
    if (output / (args.mode + ".json")).exists():
        raise SystemExit("Evidence already exists; choose another --output directory")
    secret = dotenv_values(root / ".env").get("DEV_ADMIN_TOKEN")
    if not secret:
        raise SystemExit("Local development credential missing")
    raw_script = (root / "tests/load/stage5.js").read_bytes()
    saved = output / "stage5.js"
    if saved.exists() and saved.read_bytes() != raw_script:
        raise SystemExit("Measurement script changed; choose a new --output directory")
    cohort = save_cohort(raw_cohort, output, evidence / "cohorts", pin=True)
    if not saved.exists():
        saved.write_bytes(raw_script)
    environment = dict(os.environ)
    environment.update(
        WORKSPACE_A=dev_token(secret, DEV_ACTORS[0]),
        WORKSPACE_B=dev_token(secret, DEV_ACTORS[1]),
        MODE=args.mode,
    )
    command = [
        "docker",
        "run",
        "--rm",
        "--cpus=2",
        "--memory=512m",
        "--label",
        "radar.stage5.generator=true",
        "--network",
        "open-source-radar_backend",
        "--mount",
        f"type=bind,source={output},target=/tests,readonly",
        "--mount",
        f"type=bind,source={output},target=/results",
        "--mount",
        f"type=bind,source={cohort},target=/data/cohort.json,readonly",
        "-e",
        "WORKSPACE_A",
        "-e",
        "WORKSPACE_B",
        "-e",
        "MODE",
        IMAGE,
        "run",
        "--quiet",
        "/tests/stage5.js",
    ]
    started = datetime.now(UTC).isoformat()
    stop = threading.Event()
    observer = None
    if args.monitor:
        from scripts.measure_stage5 import observe_resources

        observer = threading.Thread(
            target=observe_resources, args=(stop, output / "resources.jsonl"), daemon=True
        )
        observer.start()
    try:
        with prevent_idle_sleep() as awake:
            result = subprocess.run(command, env=environment, check=False)
    finally:
        stop.set()
        if observer:
            observer.join(timeout=15)
    record = {
        "mode": args.mode,
        "started_at": started,
        "completed_at": datetime.now(UTC).isoformat(),
        "exit_code": result.returncode,
        "image": IMAGE,
        "generator_cpu_limit": 2,
        "generator_memory_bytes": 536870912,
        "shared_host": True,
        "test_actors": 2,
        "private_operations": "read-only",
        "cohort_packages": cohort_size,
        "cohort_sha256": hashlib.sha256(raw_cohort).hexdigest(),
        "script_sha256": hashlib.sha256(raw_script).hexdigest(),
        "idle_sleep_prevention": awake,
    }
    (output / (args.mode + "-run.json")).write_text(
        json.dumps(record, indent=2) + "\n", encoding="utf-8"
    )
    raise SystemExit(result.returncode)


if __name__ == "__main__":
    main()
