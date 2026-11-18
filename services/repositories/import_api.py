from datetime import datetime
from uuid import UUID

import strawberry
from radar_common.database import engine
from radar_common.graphql import db_call
from radar_common.import_api import SourceImportJob, require_admin, work_view
from radar_common.import_queue import enqueue
from radar_common.telemetry import correlation_id
from sqlalchemy.orm import Session
from strawberry.types import Info

from services.repositories.source import candidates


@strawberry.type
class Mutation:
    @strawberry.mutation
    async def request_repository_import(
        self,
        info: Info,
        request_key: UUID,
        package_id: strawberry.ID,
        urls: list[str],
        observed_at: datetime,
        max_repositories: int = 5,
    ) -> SourceImportJob:
        require_admin(info)
        if (
            not str(package_id).startswith("pypi:")
            or len(str(package_id)) > 220
            or len(urls) > 100
            or any(len(url) > 4096 for url in urls)
            or observed_at.tzinfo is None
            or not 1 <= max_repositories <= 5
        ):
            raise ValueError("Invalid repository import input")
        candidates(urls)
        payload: dict = {
            "package": str(package_id),
            "urls": urls,
            "observed": observed_at.isoformat(),
        }
        if max_repositories != 5:
            payload["max_repositories"] = max_repositories
        correlation = correlation_id.get()

        def create() -> SourceImportJob:
            with Session(engine()) as session, session.begin():
                return work_view(enqueue(session, request_key, payload, correlation))

        return await db_call(create)
