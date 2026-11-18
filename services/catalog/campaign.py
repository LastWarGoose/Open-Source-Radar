"""Bounded, resumable campaigns stored in the existing Catalog job journal."""

import hashlib
import json
from datetime import UTC, datetime
from uuid import UUID, uuid4, uuid5

import strawberry
from radar_common.database import engine
from radar_common.graphql import db_call, invalid
from radar_common.import_api import require_admin
from radar_common.import_queue import Work, enqueue
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session
from strawberry.types import Info

from services.catalog.domain_models import ImportJobRow
from services.catalog.normalization import normalized_name


def advance(session: Session, row: ImportJobRow) -> None:
    manifest = dict(row.checkpoint["campaign"])
    counts = dict(
        session.execute(
            select(Work.status, func.count()).where(Work.parent_id == row.id).group_by(Work.status)
        ).all()
    )
    succeeded, pending = counts.get("succeeded", 0), counts.get("queued", 0)
    row.processed = succeeded
    # Work rows are the durable cursor; do not rewrite the large manifest per package.
    position = sum(counts.values())
    names = manifest["names"]
    target = manifest["target"]
    # At most 40 uncompleted packages, never more successes than the target.
    amount = min(40 - pending, target - succeeded - pending, len(names) - position)
    for offset in range(max(0, amount)):
        index = position + offset
        payload = {
            "name": names[index],
            "version": None,
            "stable_only": True,
            "repositories": index < 10000 and index % 500 == 0,
            "repository_limit": 1,
        }
        enqueue(session, uuid5(row.id, str(index)), payload, "campaign-" + row.id.hex, row.id)
    position += max(0, amount)
    pending += max(0, amount)
    row.status = (
        "succeeded"
        if succeeded >= target
        else "failed"
        if not pending and position == len(names)
        else "running"
    )
    row.error_code = "CANDIDATES_EXHAUSTED" if row.status == "failed" else None
    row.completed_at = (
        row.completed_at or datetime.now(UTC) if row.status in ("failed", "succeeded") else None
    )


@strawberry.type
class ImportCampaign:
    id: UUID
    status: str
    target: int
    succeeded: int
    failed: int
    pending: int
    candidates_consumed: int
    candidates_total: int
    manifest_hash: str
    created_at: datetime
    completed_at: datetime | None


def view(session: Session, row: ImportJobRow) -> ImportCampaign:
    manifest = row.checkpoint["campaign"]
    counts = dict(
        session.execute(
            select(Work.status, func.count()).where(Work.parent_id == row.id).group_by(Work.status)
        ).all()
    )
    return ImportCampaign(
        id=row.id,
        status=row.status,
        target=manifest["target"],
        succeeded=counts.get("succeeded", 0),
        failed=counts.get("failed", 0),
        pending=counts.get("queued", 0),
        candidates_consumed=sum(counts.values()),
        candidates_total=len(manifest["names"]),
        manifest_hash=manifest["hash"],
        created_at=row.created_at,
        completed_at=row.completed_at,
    )


def create(key: UUID, names: list[str], target: int) -> ImportCampaign:
    if not 1 <= target <= 10000 or not target <= len(names) <= 15000:
        raise invalid("Select up to 15000 candidates and a target of 1 to 10000")
    normalized = [normalized_name(name) for name in names]
    if len(set(normalized)) != len(normalized):
        raise invalid("Campaign candidates must be unique")
    digest = hashlib.sha256(
        json.dumps([normalized, target], separators=(",", ":")).encode()
    ).hexdigest()
    with Session(engine()) as session, session.begin():
        session.execute(
            insert(ImportJobRow)
            .values(
                id=uuid4(),
                request_key=key,
                status="queued",
                source="PYPI",
                processed=0,
                checkpoint={
                    "campaign": {
                        "names": normalized,
                        "target": target,
                        "hash": digest,
                    }
                },
            )
            .on_conflict_do_nothing(index_elements=[ImportJobRow.request_key])
        )
        row = session.scalar(
            select(ImportJobRow).where(ImportJobRow.request_key == key).with_for_update()
        )
        assert row
        if row.checkpoint.get("campaign", {}).get("hash") != digest:
            raise invalid("Idempotency key already used with another manifest")
        advance(session, row)
        return view(session, row)


async def request_campaign(
    info: Info, request_key: UUID, names: list[str], target: int = 10000
) -> ImportCampaign:
    require_admin(info)
    return await db_call(create, request_key, names, target)


async def import_campaign(info: Info, id: UUID) -> ImportCampaign | None:
    require_admin(info)

    def read() -> ImportCampaign | None:
        with Session(engine()) as session:
            row = session.get(ImportJobRow, id)
            return view(session, row) if row and "campaign" in row.checkpoint else None

    return await db_call(read)
