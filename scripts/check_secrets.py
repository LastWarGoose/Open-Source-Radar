"""Check the worktree and app logs for the generated local credentials, without echoing them."""

import argparse
import subprocess
from pathlib import Path

from dotenv import dotenv_values


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--logs", action="store_true")
    args = parser.parse_args()
    values = [
        value
        for key, value in dotenv_values(".env").items()
        if value and ("PASSWORD" in key or "TOKEN" in key)
    ]
    paths = (
        subprocess.check_output(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"]
        )
        .decode()
        .split("\0")
    )
    leaks = []
    for name in filter(None, paths):
        content = Path(name).read_bytes()
        if any(value.encode() in content for value in values):
            leaks.append(name)
    if args.logs:
        result = subprocess.run(
            ["docker", "compose", "logs", "--no-color"], capture_output=True, check=True
        )
        if any(value.encode() in result.stdout + result.stderr for value in values):
            leaks.append("compose logs")
    if leaks:
        raise SystemExit("Credential exposure detected in: " + ", ".join(leaks))
    print(
        "PASS: generated credentials absent from non-ignored files"
        + (" and Compose logs" if args.logs else "")
    )


if __name__ == "__main__":
    main()
