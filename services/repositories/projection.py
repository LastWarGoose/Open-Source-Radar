from datetime import datetime

import strawberry
from radar_common.database import engine
from radar_common.graphql import db_call, invalid
from radar_common.import_api import require_admin
from radar_common.import_queue import SourceState
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from strawberry.types import Info

from services.repositories.models import PackageRepositoryRow, RepositoryRow


@strawberry.type
class RepositorySnapshot:
    package_id: strawberry.ID
    stars: int | None
    checked_at: datetime
    status: str


def snapshots(ids: list[str]) -> list[RepositorySnapshot]:
    with Session(engine()) as session:
        states = list(session.scalars(select(SourceState).where(SourceState.key.in_(ids))))
        metadata = {
            key: (stars, fetched)
            for key, stars, fetched in session.execute(
                select(
                    PackageRepositoryRow.package_id,
                    func.max(RepositoryRow.stars),
                    func.max(RepositoryRow.fetched_at),
                )
                .join(RepositoryRow)
                .where(
                    PackageRepositoryRow.package_id.in_(ids),
                    PackageRepositoryRow.status == "VERIFIED",
                    RepositoryRow.source == "GITHUB",
                )
                .group_by(PackageRepositoryRow.package_id)
            ).all()
        }
        return [
            RepositorySnapshot(
                package_id=strawberry.ID(row.key),
                stars=metadata.get(row.key, (None, None))[0],
                # A shared repository can change via another package's import.
                checked_at=max(row.checked_at, metadata.get(row.key, (None, row.checked_at))[1]),
                status=row.status,
            )
            for row in states
        ]


async def repository_snapshots(
    info: Info, package_ids: list[strawberry.ID]
) -> list[RepositorySnapshot]:
    require_admin(info)
    if not 1 <= len(package_ids) <= 100 or any(len(value) > 220 for value in package_ids):
        raise invalid("Select 1 to 100 package IDs")
    return await db_call(snapshots, [str(value) for value in package_ids])
