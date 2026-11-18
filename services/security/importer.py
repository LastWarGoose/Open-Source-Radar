from datetime import UTC, datetime
from uuid import NAMESPACE_URL, uuid5

from radar_common.database import engine
from radar_common.import_queue import Work, record_state
from radar_common.source_http import SourceHTTP
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from services.security.models import FindingRow, VersionScanRow
from services.security.source import fetch
from services.security.store import save_advisory


def process(work: Work, http: SourceHTTP) -> None:
    now = datetime.now(UTC)
    advisories = fetch(http, work.payload["name"], work.payload["version"])
    with Session(engine()) as session, session.begin():
        if not record_state(
            session, work.payload["release"], datetime.fromisoformat(work.payload["observed"])
        ):
            return
        row = session.scalar(
            select(VersionScanRow).where(VersionScanRow.release_id == work.payload["release"])
        )
        if row is None:
            row = VersionScanRow(
                id=uuid5(NAMESPACE_URL, "scan:" + work.payload["release"]),
                release_id=work.payload["release"],
                source="OSV",
                status="UNKNOWN",
            )
            session.add(row)
        row.status, row.source, row.checked_at = "SUCCESS", "OSV", now
        row.package_name, row.version = work.payload["name"], work.payload["version"]
        row.last_success_at, row.error_code = now, None
        session.flush()
        session.execute(delete(FindingRow).where(FindingRow.scan_id == row.id))
        fixes: dict[str, set[str]] = {}
        for advisory in advisories:
            key = save_advisory(
                session,
                advisory.id,
                advisory.aliases,
                advisory.summary or advisory.details[:1000],
                now,
            )
            versions = fixes.setdefault(key, set())
            fixed = advisory.fix_for(work.payload["name"], work.payload["version"])
            if fixed:
                versions.add(fixed)
        for key, versions in fixes.items():
            session.add(
                FindingRow(
                    scan_id=row.id,
                    vulnerability_id=key,
                    fixed_version=next(iter(versions)) if len(versions) == 1 else None,
                )
            )


def failed(session: Session, work: Work, code: str) -> None:
    if not record_state(
        session, work.payload["release"], datetime.fromisoformat(work.payload["observed"]), code
    ):
        return
    row = session.scalar(
        select(VersionScanRow).where(VersionScanRow.release_id == work.payload["release"])
    )
    if row is None:
        row = VersionScanRow(
            id=uuid5(NAMESPACE_URL, "scan:" + work.payload["release"]),
            release_id=work.payload["release"],
            source="OSV",
            status="UNKNOWN",
        )
        session.add(row)
    row.status = "STALE" if row.last_success_at else "FAILED"
    row.package_name, row.version = work.payload["name"], work.payload["version"]
    row.checked_at, row.error_code = datetime.now(UTC), code
