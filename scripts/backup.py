"""Logical service backups. Restore only into empty databases of a different Compose project."""

import argparse
import hashlib
import json
import re
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path

DATABASES = ("catalog", "repositories", "security", "workspace")


def command(project: str, *args: str) -> list[str]:
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", project):
        raise ValueError("Invalid Compose project")
    return ["docker", "compose", "-p", project, "exec", "-T", "postgres", *args]


def checksum(path: Path) -> str:
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def backup(project: str, directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=False, mode=0o700)
    digests = {}
    started = datetime.now(UTC).isoformat()
    for db in DATABASES:
        target = directory / f"{db}.dump"
        with target.open("xb") as out:
            subprocess.run(command(project, "pg_dump", "-U", db, "-Fc", db), stdout=out, check=True)
        digests[db] = checksum(target)
    (directory / "manifest.json").write_text(
        json.dumps({"project": project, "started": started, "sha256": digests}), encoding="utf-8"
    )


def restore(project: str, directory: Path) -> None:
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    if manifest["project"] == project:
        raise ValueError("Restore requires a separate project")
    for db in DATABASES:
        if checksum(directory / f"{db}.dump") != manifest["sha256"][db]:
            raise ValueError(f"Checksum mismatch for {db}")
        sql = "select count(*) from pg_tables where schemaname='public'"
        occupied = subprocess.check_output(command(project, "psql", "-U", db, "-Atc", sql))
        if occupied.strip() != b"0":
            raise ValueError(f"Restore target {db} must be empty")
    for db in DATABASES:
        with (directory / f"{db}.dump").open("rb") as src:
            subprocess.run(
                command(project, "pg_restore", "-1", "-e", "-U", db, "-d", db),
                stdin=src,
                check=True,
            )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["backup", "restore"])
    parser.add_argument("project")
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    start = time.monotonic()
    (backup if args.action == "backup" else restore)(args.project, args.directory)
    print(f"{args.action}: {len(DATABASES)} databases, {time.monotonic() - start:.1f}s")
