import os
from datetime import UTC, datetime

import httpx
import strawberry
from pydantic import BaseModel, Field
from radar_common.database import engine
from radar_common.graphql import db_call, invalid
from radar_common.import_api import require_admin
from radar_common.tracing import trace_headers
from sqlalchemy import select, text, update
from sqlalchemy.orm import Session
from strawberry.types import Info

from services.catalog.domain_models import PackageRow


class Snapshot(BaseModel):
    packageId: str = Field(max_length=220)
    stars: int | None = Field(ge=0)
    checkedAt: datetime
    status: str


def apply_snapshot(session: Session, snapshot: Snapshot) -> bool:
    if snapshot.checkedAt.tzinfo is None or snapshot.status not in (
        "UNKNOWN",
        "SUCCESS",
        "STALE",
        "FAILED",
    ):
        raise ValueError("Invalid projection")
    result = session.execute(
        update(PackageRow)
        .where(
            PackageRow.id == snapshot.packageId,
            (PackageRow.github_checked_at.is_(None))
            | (PackageRow.github_checked_at < snapshot.checkedAt),
        )
        .values(
            github_stars=snapshot.stars,
            github_checked_at=snapshot.checkedAt,
            github_projected_at=datetime.now(UTC),
            github_status=snapshot.status,
        )
        .returning(PackageRow.id)
    )
    return result.scalar_one_or_none() is not None


@strawberry.input
class RepositoryProjectionInput:
    package_id: strawberry.ID
    stars: int | None
    checked_at: datetime
    status: str


async def update_repository_projection(info: Info, snapshot: RepositoryProjectionInput) -> bool:
    require_admin(info)
    try:
        value = Snapshot(
            packageId=str(snapshot.package_id),
            stars=snapshot.stars,
            checkedAt=snapshot.checked_at,
            status=snapshot.status,
        )
        if value.checkedAt.tzinfo is None or value.status not in (
            "UNKNOWN",
            "SUCCESS",
            "STALE",
            "FAILED",
        ):
            raise ValueError("Invalid projection")
    except ValueError:
        raise invalid("Invalid repository projection") from None

    def save() -> bool:
        with Session(engine()) as session, session.begin():
            return apply_snapshot(session, value)

    return await db_call(save)


def reconcile() -> int:
    # Only local Catalog rows are read here; repository data arrives through GraphQL.
    with engine().connect() as lock:
        if not lock.scalar(text("SELECT pg_try_advisory_lock(72164004)")):
            return 0
        lock.commit()
        try:
            with Session(engine()) as session:
                after = session.scalar(text("SELECT after_id FROM projection_sync WHERE id=1"))
                query = (
                    select(PackageRow.id).where(PackageRow.source == "PYPI").order_by(PackageRow.id)
                )
                if after:
                    query = query.where(PackageRow.id > after)
                ids = list(session.scalars(query.limit(100)))
            if not ids:
                with Session(engine()) as session, session.begin():
                    session.execute(text("UPDATE projection_sync SET after_id=NULL WHERE id=1"))
                return 0
            response = httpx.post(
                "http://repositories:8000/graphql",
                timeout=15,
                headers={"x-dev-admin-token": os.environ["DEV_ADMIN_TOKEN"], **trace_headers()},
                json={
                    "query": """query Reconcile($ids: [ID!]!) {
                    repositorySnapshots(packageIds: $ids) { packageId stars checkedAt status }
                }""",
                    "variables": {"ids": ids},
                },
            )
            response.raise_for_status()
            data = response.json()
            if data.get("errors"):
                raise ValueError("Projection source unavailable")
            values = [Snapshot.model_validate(row) for row in data["data"]["repositorySnapshots"]]
            if any(row.packageId not in ids for row in values):
                raise ValueError("Unexpected projection key")
            with Session(engine()) as session, session.begin():
                for value in values:
                    apply_snapshot(session, value)
                session.execute(
                    text("UPDATE projection_sync SET after_id=:after,checked_at=:now WHERE id=1"),
                    {"after": ids[-1] if len(ids) == 100 else None, "now": datetime.now(UTC)},
                )
            return len(values)
        finally:
            lock.execute(text("SELECT pg_advisory_unlock(72164004)"))
            lock.commit()
