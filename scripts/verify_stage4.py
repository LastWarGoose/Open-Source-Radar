"""Browser + DB checks with temporary fixtures and restored service availability."""

import os
import subprocess

from scripts.verify_infrastructure import compose
from scripts.verify_stage3 import CONSUMERS


def fixtures(phase: str) -> None:
    compose("run", "--rm", "checks", ".venv/bin/python", "-m", "scripts.check_stage4", phase)


def main() -> None:
    try:
        compose("stop", *CONSUMERS)
        fixtures("seed")
        fixtures("check")
        subprocess.run(["node", "node_modules/@playwright/test/cli.js", "test"], check=True)
        for service in ("security", "repositories", "catalog"):
            try:
                compose("stop", service)
                subprocess.run(
                    [
                        "node",
                        "node_modules/@playwright/test/cli.js",
                        "test",
                        "--config=playwright.partial.config.ts",
                    ],
                    check=True,
                    env={**os.environ, "FAILED_SERVICE": service},
                )
            finally:
                compose("up", "-d", "--wait", service)
    finally:
        try:
            fixtures("cleanup")
        finally:
            compose("up", "-d", "--wait", *CONSUMERS)
    print(
        "PASS: stage 4 public UI, projection and real service outage checks; "
        "fixtures removed and services restored",
        flush=True,
    )


if __name__ == "__main__":
    main()
