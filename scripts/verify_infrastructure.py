"""Exercise only this project's development services; preserve all named volumes."""

import json
import subprocess
import time
from uuid import uuid4


def compose(*args: str) -> str:
    result = subprocess.run(
        ["docker", "compose", *args],
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
    )
    if result.returncode:
        print(result.stdout)
        print(result.stderr)
        raise RuntimeError("Compose verification step failed: " + " ".join(args[:3]))
    print(result.stdout, end="", flush=True)
    return result.stdout


def check(action: str, key: str) -> None:
    compose(
        "run",
        "--rm",
        "checks",
        ".venv/bin/python",
        "-m",
        "scripts.check_stage1",
        "--phase",
        action,
        "--key",
        key,
    )


def check_delivery_logs(job_id: str) -> None:
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        output = subprocess.check_output(
            ["docker", "compose", "logs", "--no-color", "--no-log-prefix", "worker", "dispatcher"],
            text=True,
            encoding="utf-8",
        )
        records = [json.loads(line) for line in output.splitlines() if line.startswith("{")]
        records = [record for record in records if record.get("job_id") == job_id]
        duplicates = [record for record in records if record.get("event") == "duplicate_ignored"]
        if len(duplicates) >= 2:
            published = [record for record in records if record.get("event") == "job_published"]
            completed = [record for record in records if record.get("event") == "probe_completed"]
            assert len(completed) == 1 and published
            assert completed[0]["correlation_id"] == published[0]["correlation_id"]
            assert completed[0]["correlation_id"].startswith("stage1-")
            print("PASS: two duplicate deliveries ignored; dispatcher/worker correlation matches")
            return
        time.sleep(0.25)
    raise AssertionError("Duplicate deliveries were not observed in worker logs")


def main() -> None:
    compose("run", "--rm", "migrate")
    output = compose("run", "--rm", "checks")
    assert "PASS:" in output
    job_id = next(
        line.split("=", 1)[1] for line in output.splitlines() if line.startswith("PROBE_JOB_ID=")
    )
    check_delivery_logs(job_id)
    key = str(uuid4())
    try:
        compose("stop", "rabbitmq")
        check("enqueue", key)
        time.sleep(5)
        check("pending", key)
        compose("start", "rabbitmq")
        compose("up", "-d", "--wait", "rabbitmq", "worker", "dispatcher")
        check("complete", key)
        # Queue a message while workers are stopped, then restart the broker.
        queued_key = str(uuid4())
        compose("stop", "worker")
        check("enqueue", queued_key)
        check("published", queued_key)
        compose("restart", "rabbitmq")
        compose("up", "-d", "--wait", "rabbitmq", "dispatcher")
        compose("start", "worker")
        check("complete", queued_key)
        # Recreate all containers, retaining their named volumes.
        compose("down")
        compose("up", "-d", "--wait")
        check("complete", key)
        check("complete", queued_key)
        print(
            "PASS: broker outage recovery, persistent queue, full container recreation", flush=True
        )
    finally:
        compose("up", "-d", "--wait")


if __name__ == "__main__":
    main()
