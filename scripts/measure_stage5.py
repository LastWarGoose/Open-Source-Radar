"""Measure only a completed real campaign; always restore stopped local services."""

import argparse
import json
import platform
import subprocess
import sys
import threading
from datetime import UTC, datetime
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "docs/evidence/stage5"
CONSUMERS = ["beat", "catalog-importer", "repositories-importer", "security-importer"]


def observe_resources(stop: threading.Event, output: Path) -> None:
    with output.open("w", encoding="utf-8") as stream:
        while not stop.is_set():
            identities = subprocess.run(
                ["docker", "compose", "ps", "-q"],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
            ids = identities.stdout.split()
            generators = subprocess.run(
                ["docker", "ps", "--filter", "label=radar.stage5.generator=true", "-q"],
                capture_output=True,
                text=True,
                check=False,
            )
            ids.extend(generators.stdout.split())
            sample = (
                subprocess.run(
                    ["docker", "stats", "--no-stream", "--format", "{{json .}}", *ids],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                if ids
                else None
            )
            record = {"at": datetime.now(UTC).isoformat(), "containers": []}
            if sample and sample.returncode == 0:
                record["containers"] = [json.loads(line) for line in sample.stdout.splitlines()]
            stream.write(json.dumps(record) + "\n")
            stream.flush()
            stop.wait(10)


def compose(*arguments: str, bulk: bool = False) -> None:
    command = ["docker", "compose", "-f", "compose.yaml"]
    if (ROOT / "compose.override.yaml").exists():
        command.extend(["-f", "compose.override.yaml"])
    if bulk:
        command.extend(["-f", "compose.bulk.yaml"])
    subprocess.run([*command, *arguments], cwd=ROOT, check=True)


def checks(module: str, *arguments: str) -> None:
    compose(
        "run",
        "--rm",
        "--volume",
        f"{ROOT / 'scripts'}:/app/scripts:ro",
        "--volume",
        f"{OUTPUT}:/evidence",
        "checks",
        ".venv/bin/python",
        "-m",
        module,
        *arguments,
    )


def environment() -> dict:
    info = json.loads(
        subprocess.check_output(["docker", "info", "--format", "{{json .}}"], text=True)
    )
    images = json.loads(
        subprocess.check_output(["docker", "compose", "images", "--format", "json"], text=True)
    )
    head = subprocess.run(["git", "rev-parse", "--verify", "HEAD"], capture_output=True, text=True)
    return {
        "captured_at": datetime.now(UTC).isoformat(),
        "host_os": platform.platform(),
        "docker": {
            key: info.get(key)
            for key in (
                "NCPU",
                "MemTotal",
                "OperatingSystem",
                "KernelVersion",
                "Architecture",
                "ServerVersion",
                "Driver",
            )
        },
        "images": images,
        "commit": head.stdout.strip() if head.returncode == 0 else None,
        "source_state": "uncommitted workspace; see source-hashes.json",
        "replicas_per_service": 1,
        "shared_generator_host": True,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("campaign")
    parser.add_argument("--run-name", default="load-final")
    args = parser.parse_args()
    target = OUTPUT / args.run_name
    if target.exists():
        raise SystemExit("Run directory already exists; use another --run-name")
    checks("scripts.report_stage5", args.campaign)
    report = json.loads((OUTPUT / "source-report.json").read_text(encoding="utf-8"))
    if report["campaign"]["status"] != "succeeded" or report["cohort_unique_packages"] < 10000:
        raise SystemExit("Real campaign is not complete")
    if any(report[source]["cohort_jobs"].get("queued", 0) for source in ("github", "osv")):
        raise SystemExit("Wait for enrichment jobs to finish before baseline")
    if any(report[source]["cohort_missing_jobs"] for source in ("github", "osv")):
        raise SystemExit("Expected enrichment jobs are missing; investigate before measurements")
    target.mkdir()
    (OUTPUT / "environment.json").write_text(
        json.dumps(environment(), indent=2) + "\n", encoding="utf-8"
    )
    codes: dict[str, int] = {}
    stop = threading.Event()
    observer = threading.Thread(
        target=observe_resources, args=(stop, target / "resources.jsonl"), daemon=True
    )
    observer.start()

    def load(mode: str, directory: Path = target) -> None:
        print(f"MEASURE {mode}: {datetime.now(UTC).isoformat()}", flush=True)
        result = subprocess.run(
            [sys.executable, "-m", "scripts.load_stage5", mode, "--output", str(directory)],
            cwd=ROOT,
            check=False,
        )
        codes[mode if directory == target else directory.name] = result.returncode
        if result.returncode and mode in ("cold", "warm"):
            raise RuntimeError("Pre-baseline validation failed; inspect saved evidence")

    try:
        compose("stop", *CONSUMERS)
        checks("scripts.report_stage5", args.campaign)
        checks("scripts.sql_stage5")
        checks("scripts.enqueue_stage5")
        compose("restart", "catalog", "repositories", "security", "workspace", "gateway")
        compose(
            "up",
            "-d",
            "--no-deps",
            "--wait",
            "catalog",
            "repositories",
            "security",
            "workspace",
            "gateway",
        )
        for mode in ("cold", "warm", "baseline", "stress"):
            load(mode)
        try:
            compose("stop", "redis")
            load("smoke", target / "redis-unavailable")
        finally:
            compose("up", "-d", "--no-deps", "--wait", "redis")
    finally:
        stop.set()
        observer.join(timeout=15)
        # The completed campaign no longer needs the elevated bulk budgets.
        compose("up", "-d", "--no-deps", "--wait", *CONSUMERS)
        (target / "exit-codes.json").write_text(
            json.dumps(codes, indent=2) + "\n", encoding="utf-8"
        )
    with httpx.Client(timeout=30) as client:
        assert client.get("http://localhost:3000").status_code == 200
        response = client.post(
            "http://localhost:4000/graphql", json={"query": "query { __typename }"}
        )
        assert response.status_code == 200 and not response.json().get("errors")
    print("MEASURE complete; local site and source consumers restored", flush=True)
    if any(codes.values()):
        raise SystemExit("Some measurement thresholds failed; inspect evidence")


if __name__ == "__main__":
    main()
