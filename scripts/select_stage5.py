"""One bounded official index download; deterministic name sample, not popularity."""

import argparse
import gzip
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import httpx

from services.catalog.normalization import normalized_name

SEED = "open-source-radar-stage5-v1"


def select_names(projects: list[dict], count: int) -> list[str]:
    names = set()
    for project in projects:
        try:
            names.add(normalized_name(project["name"]))
        except (ValueError, KeyError, TypeError):
            continue
    return sorted(
        names, key=lambda name: (hashlib.sha256((SEED + "\0" + name).encode()).digest(), name)
    )[:count]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="docs/evidence/stage5/selection.json")
    parser.add_argument("--snapshot", default=".runtime/stage5/pypi-index.json.gz")
    args = parser.parse_args()
    output, snapshot = Path(args.output), Path(args.snapshot)
    if output.exists():
        raise SystemExit("Selection already exists; reuse it to resume the same cohort")
    data = bytearray()
    with httpx.Client(timeout=httpx.Timeout(120, connect=10), follow_redirects=False) as client:
        with client.stream(
            "GET",
            "https://pypi.org/simple/",
            headers={
                "Accept": "application/vnd.pypi.simple.v1+json",
                "User-Agent": "OpenSourceRadar/0.1 (one bounded index snapshot)",
            },
        ) as response:
            response.raise_for_status()
            for chunk in response.iter_bytes():
                data.extend(chunk)
                if len(data) > 128_000_000:
                    raise ValueError("Index exceeds the 128 MB budget")
            etag = response.headers.get("etag")
            serial = response.headers.get("x-pypi-last-serial")
    document = json.loads(data)
    names = select_names(document["projects"], 15000)
    if len(names) != 15000:
        raise ValueError("Not enough candidates")
    manifest = {
        "source": "https://pypi.org/simple/",
        "captured_at": datetime.now(UTC).isoformat(),
        "etag": etag,
        "serial": serial,
        "index_sha256": hashlib.sha256(data).hexdigest(),
        "index_projects": len(document["projects"]),
        "seed": SEED,
        "target": 10000,
        "policy": "SHA256(seed + NUL + normalized_name), first 10000 successful stable-release "
        "imports; 15000 candidate cap",
        "github_policy": "candidate positions 0,500,...9500 only; "
        "at most one declared repository per sampled package",
        "names": names,
    }
    snapshot.parent.mkdir(parents=True, exist_ok=True)
    snapshot.write_bytes(gzip.compress(bytes(data), mtime=0))
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"PASS: saved immutable index snapshot and {len(names)} candidates; serial {serial}")


if __name__ == "__main__":
    main()
