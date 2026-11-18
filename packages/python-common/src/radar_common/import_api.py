import hmac
import os
from datetime import datetime
from uuid import UUID

import strawberry
from graphql import GraphQLError
from sqlalchemy.orm import Session
from strawberry.types import Info

from radar_common.database import engine
from radar_common.graphql import db_call
from radar_common.import_queue import Work


def require_admin(info: Info) -> None:
    request = info.context.get("request")
    expected = os.getenv("DEV_ADMIN_TOKEN", "")
    supplied = request.headers.get("x-dev-admin-token", "") if request else ""
    if not expected or not hmac.compare_digest(expected, supplied):
        raise GraphQLError(
            "Development administrator token required", extensions={"code": "FORBIDDEN"}
        )


@strawberry.federation.type(shareable=True)
class SourceImportJob:
    id: UUID
    status: str
    attempts: int
    error_code: str | None
    next_attempt_at: datetime


def work_view(row: Work) -> SourceImportJob:
    return SourceImportJob(
        id=row.id,
        status=row.status,
        attempts=row.attempts,
        error_code=row.error_code,
        next_attempt_at=row.next_at,
    )


async def read_work(info: Info, id: UUID) -> SourceImportJob | None:
    require_admin(info)

    def read() -> SourceImportJob | None:
        with Session(engine()) as session:
            row = session.get(Work, id)
            return work_view(row) if row else None

    return await db_call(read)
