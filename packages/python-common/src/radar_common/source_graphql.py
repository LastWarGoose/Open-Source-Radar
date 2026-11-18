from datetime import UTC, datetime, timedelta

import strawberry
from sqlalchemy import select
from sqlalchemy.orm import Session
from strawberry.dataloader import DataLoader

from radar_common.database import engine
from radar_common.graphql import db_call
from radar_common.import_queue import SourceState


@strawberry.federation.type(shareable=True)
class SourceFreshness:
    status: str
    checked_at: datetime | None
    last_success_at: datetime | None
    error_code: str | None


def freshness_loader() -> DataLoader[str, SourceState | None]:
    async def load(keys: list[str]) -> list[SourceState | None]:
        def read() -> list[SourceState | None]:
            with Session(engine()) as session:
                rows = {
                    row.key: row
                    for row in session.scalars(select(SourceState).where(SourceState.key.in_(keys)))
                }
                return [rows.get(key) for key in keys]

        return await db_call(read)

    return DataLoader(load_fn=load, max_batch_size=100)


def freshness_view(row: SourceState | None) -> SourceFreshness:
    if row is None:
        return SourceFreshness(
            status="UNKNOWN", checked_at=None, last_success_at=None, error_code=None
        )
    stale = row.last_success_at and row.last_success_at < datetime.now(UTC) - timedelta(days=1)
    return SourceFreshness(
        status="STALE" if row.status == "SUCCESS" and stale else row.status,
        checked_at=row.checked_at,
        last_success_at=row.last_success_at,
        error_code=row.error_code,
    )
