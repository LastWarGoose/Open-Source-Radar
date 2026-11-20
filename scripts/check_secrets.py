"""Check the worktree and app logs for the generated local credentials, without echoing them."""

import argparse
import gzip
import subprocess
from io import BufferedIOBase
from pathlib import Path

from dotenv import dotenv_values


def contains_secret(stream: BufferedIOBase, values: list[bytes]) -> bool:
    if not values:
        return False
    overlap = max(map(len, values)) - 1
    tail = b""
    while chunk := stream.read(64 * 1024):
        data = tail + chunk
        if any(value in data for value in values):
            return True
        tail = data[-overlap:] if overlap else b""
    return False


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--logs", action="store_true")
    args = parser.parse_args()
    values = [
        value.encode()
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
        path = Path(name)
        with path.open("rb") as stream:
            found = contains_secret(stream, values)
        if not found and path.suffix == ".gz":
            with gzip.open(path, "rb") as archive:
                found = contains_secret(archive, values)
        if found:
            leaks.append(name)
    if args.logs:
        result = subprocess.run(
            ["docker", "compose", "logs", "--no-color"], capture_output=True, check=True
        )
        if any(value in result.stdout + result.stderr for value in values):
            leaks.append("compose logs")
    if leaks:
        raise SystemExit("Credential exposure detected in: " + ", ".join(leaks))
    print(
        "PASS: generated credentials absent from non-ignored files"
        + (" and Compose logs" if args.logs else "")
    )


if __name__ == "__main__":
    main()
