"""Service-failure checks on disposable stage-7 containers. No external API access."""

import subprocess
import time
from collections.abc import Callable
from uuid import UUID, uuid4

import httpx

from scripts.load_stage7 import PROJECT, ROOT, URL

COMPOSE = [
    "docker",
    "compose",
    "-p",
    PROJECT,
    "-f",
    "compose.yaml",
    "-f",
    "compose.observability.yaml",
    "-f",
    "compose.stage7-test.yaml",
    "--profile",
    "observability",
]


def command(*args: str) -> str:
    return subprocess.check_output([*COMPOSE, *args], text=True, encoding="utf-8")


def until(check: Callable[[], bool], seconds: int = 90) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if check():
            return
        time.sleep(0.5)
    raise AssertionError("Fault recovery exceeded deadline")


def scalar(statement: str) -> str:
    return command("exec", "-T", "postgres", "psql", "-U", "catalog", "-Atc", statement).strip()


def gql(query: str, **variables: object) -> dict:
    token = next(
        v.split("=", 1)[1]
        for v in (ROOT / ".env").read_text().splitlines()
        if v.startswith("DEV_ADMIN_TOKEN=")
    )
    response = httpx.post(
        URL,
        json={"query": query, "variables": variables},
        headers={"x-dev-admin-token": token},
        timeout=20,
    )
    response.raise_for_status()
    return dict(response.json())


def enqueue() -> UUID:
    result = gql("mutation Probe($k:UUID!){requestProbeJob(requestKey:$k){id}}", k=str(uuid4()))
    return UUID(result["data"]["requestProbeJob"]["id"])


def receipts(identity: UUID) -> str:
    return scalar(f"SELECT count(*) FROM probe_receipts WHERE job_id='{identity}'")


def worker_loss(phase: str) -> None:
    name = "radar-stage7-fault-" + phase + "-" + uuid4().hex[:10]
    command("stop", "worker")
    try:
        identity = enqueue()
        command(
            "run",
            "-d",
            "--no-deps",
            "--name",
            name,
            "-e",
            f"FAULT_JOB_ID={identity}",
            "-e",
            f"FAULT_PHASE={phase}",
            "-v",
            f"{ROOT / 'tests/fault/commit_worker.py'}:/app/commit_worker.py:ro",
            "worker",
            ".venv/bin/celery",
            "-A",
            "services.catalog.celery_app",
            "worker",
            "--include=commit_worker",
            "--concurrency=1",
            "--queues=catalog.probes",
        )
        until(lambda: receipts(identity) == "1")

        # A receipt alone cannot prove redelivery after a post-commit kill.
        def redelivered() -> bool:
            output = subprocess.run(
                ["docker", "logs", name],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            return ("duplicate_ignored" if phase == "after" else "probe_completed") in (
                output.stdout + output.stderr
            )

        until(redelivered)
        subprocess.run(["docker", "exec", name, "test", "-f", "/tmp/probe-interrupted"], check=True)
        assert receipts(identity) == "1"
        print("PASS worker loss", phase, "commit; one receipt", flush=True)
    finally:
        subprocess.run(["docker", "rm", "-f", name], stdout=subprocess.DEVNULL, check=False)
        command("start", "worker")


def main() -> None:
    assert "127.0.0.1:4400" in command("port", "gateway", "4000")
    package = 'package(id:"pypi:fastapi"){name releases(first:1){nodes{version scan{status}}}}'
    try:
        command("stop", "redis")
        for _ in range(20):
            assert gql("query Read {" + package + "}")["data"]["package"]["name"] == "fastapi"
        print("PASS 20 catalog reads with Redis stopped", flush=True)
    finally:
        command("start", "redis")
    try:
        command("stop", "security")
        result = gql("query Partial {" + package + "}")
        assert result["errors"] and result["data"]["package"]["releases"]["nodes"][0]["version"]
        print("PASS independent release fields with Security stopped", flush=True)
    finally:
        command("up", "-d", "--no-deps", "--no-recreate", "--wait", "security")
    try:
        command("stop", "rabbitmq")
        identity = enqueue()
        assert scalar(f"SELECT published_at IS NULL FROM outbox WHERE job_id='{identity}'") == "t"
    finally:
        command("up", "-d", "--no-deps", "--no-recreate", "--wait", "rabbitmq")
    until(lambda: receipts(identity) == "1")
    print("PASS recovery of job queued during broker outage", flush=True)
    command("stop", "worker")
    try:
        queued = enqueue()
        until(
            lambda: (
                scalar(f"SELECT published_at IS NOT NULL FROM outbox WHERE job_id='{queued}'")
                == "t"
            )
        )
        command("restart", "rabbitmq")
        command("up", "-d", "--no-deps", "--no-recreate", "--wait", "rabbitmq")
    finally:
        command("start", "worker")
    until(lambda: receipts(queued) == "1")
    print("PASS confirmed queued message survived broker restart", flush=True)
    for phase in ("before", "after"):
        worker_loss(phase)


if __name__ == "__main__":
    main()
