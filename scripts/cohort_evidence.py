"""Store exact load-test inputs once and pin each run to its input bytes."""

import hashlib
import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile


def _write(path: Path, content: bytes, *, exclusive: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        stream.write(content)
    try:
        # k6 and the report writer run as different users on Linux.
        temporary.chmod(0o644)
        if exclusive:
            try:
                os.link(temporary, path)
            except FileExistsError:
                if path.read_bytes() != content:
                    raise ValueError(f"Measurement input changed in {path}") from None
        else:
            temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def read_cohort(directory: Path) -> Path:
    reference = directory / "cohort.ref.json"
    if not reference.exists():
        # Existing local measurement directories may still contain their raw input.
        return (directory / "cohort.json").resolve(strict=True)
    record = json.loads(reference.read_bytes())
    payload = (directory / record["path"]).resolve(strict=True)
    if hashlib.sha256(payload.read_bytes()).hexdigest() != record["sha256"]:
        raise ValueError(f"Cohort checksum mismatch in {reference}")
    return payload


def save_cohort(content: bytes, directory: Path, store: Path, *, pin: bool = False) -> Path:
    digest = hashlib.sha256(content).hexdigest()
    payload = store / (digest + ".json")
    reference = directory / "cohort.ref.json"
    if pin and (reference.exists() or (directory / "cohort.json").exists()):
        if read_cohort(directory).read_bytes() != content:
            raise ValueError(f"Measurement input changed in {directory}")
    if payload.exists():
        if payload.read_bytes() != content:
            raise ValueError(f"Damaged cohort in {payload}")
    else:
        _write(payload, content)
    record = {"path": Path(os.path.relpath(payload, directory)).as_posix(), "sha256": digest}
    _write(reference, (json.dumps(record, indent=2) + "\n").encode(), exclusive=pin)
    return payload
