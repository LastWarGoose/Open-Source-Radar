import asyncio
from datetime import UTC, datetime
from uuid import UUID, uuid4, uuid5

import strawberry
from radar_common.database import engine
from radar_common.import_queue import Work, enqueue
from radar_common.session import require_admin
from radar_common.telemetry import correlation_id
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session
from strawberry.types import Info

from services.catalog.domain_graphql import ImportJob
from services.catalog.domain_models import ImportJobRow
from services.catalog.normalization import normalized_name, normalized_version


@strawberry.input
class ImportTarget:
    name: str
    version: str | None = None


def job_view(row: ImportJobRow) -> ImportJob:
    return ImportJob(
        id=strawberry.ID(str(row.id)),
        status=row.status,
        source=row.source,
        processed=row.processed,
        error_code=row.error_code,
        created_at=row.created_at,
        completed_at=row.completed_at,
        can_resume="campaign" not in row.checkpoint,
    )


def create_import(key: UUID, targets: list[dict], correlation: str) -> ImportJobRow:
    if not 1 <= len(targets) <= 20:
        raise ValueError("Select 1 to 20 packages")
    normalized = []
    for target in targets:
        name = normalized_name(target["name"])
        version = target.get("version")
        if version is not None:
            normalized_version(version)
        normalized.append({"name": name, "version": version})
    if len({(x["name"], x["version"]) for x in normalized}) != len(normalized):
        raise ValueError("Duplicate targets")
    with Session(engine(), expire_on_commit=False) as session, session.begin():
        identity = uuid4()
        session.execute(
            insert(ImportJobRow)
            .values(
                id=identity,
                request_key=key,
                status="queued",
                source="PYPI",
                processed=0,
                checkpoint={"targets": normalized},
            )
            .on_conflict_do_nothing(index_elements=[ImportJobRow.request_key])
        )
        row = session.scalar(select(ImportJobRow).where(ImportJobRow.request_key == key))
        assert row
        if row.checkpoint.get("targets") != normalized:
            raise ValueError("Idempotency key already used with different input")
        for index, target in enumerate(normalized):
            enqueue(session, uuid5(row.id, str(index)), target, correlation, row.id)
        return row


def refresh_parent(identity: UUID | None) -> None:
    if identity is None:
        return
    with Session(engine()) as session, session.begin():
        parent = session.scalar(
            select(ImportJobRow).where(ImportJobRow.id == identity).with_for_update()
        )
        if not parent:
            return
        if "campaign" in parent.checkpoint:
            from services.catalog.campaign import advance

            advance(session, parent)
            return
        rows = list(session.scalars(select(Work).where(Work.parent_id == identity)))
        if not rows:
            return
        parent.processed = sum(row.status == "succeeded" for row in rows)
        parent.status = (
            "failed"
            if any(row.status == "failed" for row in rows)
            else "succeeded"
            if all(row.status == "succeeded" for row in rows)
            else "running"
        )
        parent.error_code = next((row.error_code for row in rows if row.status == "failed"), None)
        parent.completed_at = (
            datetime.now(UTC) if parent.status in ("failed", "succeeded") else None
        )


async def request_import(info: Info, request_key: UUID, targets: list[ImportTarget]) -> ImportJob:
    await require_admin(info)
    row = await asyncio.to_thread(
        create_import,
        request_key,
        [{"name": x.name, "version": x.version} for x in targets],
        correlation_id.get(),
    )
    return job_view(row)


async def import_job(info: Info, id: UUID) -> ImportJob | None:
    await require_admin(info)

    def read() -> ImportJob | None:
        with Session(engine()) as session:
            row = session.get(ImportJobRow, id)
            return job_view(row) if row else None

    return await asyncio.to_thread(read)


async def resume_import(info: Info, id: UUID) -> ImportJob:
    await require_admin(info)

    def resume() -> ImportJob:
        with Session(engine()) as session, session.begin():
            row = session.get(ImportJobRow, id)
            if not row:
                raise ValueError("Unknown import")
            if "campaign" in row.checkpoint:
                raise ValueError("Resume a campaign by repeating requestCampaign with its manifest")
            for work in session.scalars(select(Work).where(Work.parent_id == id).with_for_update()):
                if work.status == "failed":
                    work.status, work.attempts, work.error_code = "queued", 0, None
                    work.next_at, work.published_at = datetime.now(UTC), None
            row.status, row.error_code, row.completed_at = "queued", None, None
            return job_view(row)

    return await asyncio.to_thread(resume)
