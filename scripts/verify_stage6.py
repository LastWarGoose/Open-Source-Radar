"""Stage 6 checks with bounded, isolated fixtures and no external source calls."""

import os
import secrets
import subprocess
from pathlib import Path
from uuid import uuid4

from scripts.verify_infrastructure import compose
from scripts.verify_stage3 import CONSUMERS


def main() -> None:
    os.environ["STAGE6_RUN"] = "radar6ui-" + uuid4().hex[:12]
    os.environ["STAGE6_PASSWORD"] = secrets.token_urlsafe(24)
    os.environ["STAGE6_JOB_KEY"] = str(uuid4())
    root = Path(__file__).resolve().parents[1]
    running = set(
        subprocess.check_output(
            ["docker", "compose", "ps", "--services", "--status", "running"], text=True
        ).splitlines()
    )
    active = [name for name in CONSUMERS if name in running]

    def check(module: str, *args: str) -> None:
        compose(
            "run",
            "--rm",
            "--no-deps",
            "-e",
            "STAGE6_RUN",
            "-e",
            "STAGE6_PASSWORD",
            "-e",
            "STAGE6_JOB_KEY",
            "--volume",
            f"{root / 'scripts'}:/app/scripts:ro",
            "checks",
            ".venv/bin/python",
            "-m",
            module,
            *args,
        )

    try:
        if active:
            compose("stop", *active)
        check("scripts.check_stage6")
        check("scripts.fixtures_stage6", "seed")
        subprocess.run(
            ["node", "node_modules/@playwright/test/cli.js", "test", "stage6.spec.ts"], check=True
        )
    finally:
        try:
            check("scripts.fixtures_stage6", "cleanup")
        finally:
            if active:
                compose("up", "-d", "--no-deps", "--no-recreate", "--wait", *active)
    print("PASS: stage 6 API/browser checks, fixtures removed, consumers restored")


if __name__ == "__main__":
    main()
