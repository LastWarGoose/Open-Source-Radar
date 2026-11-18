from datetime import datetime
from uuid import UUID

import strawberry
from packaging.utils import canonicalize_name, canonicalize_version
from packaging.version import Version
from radar_common.database import engine
from radar_common.graphql import db_call
from radar_common.import_api import SourceImportJob, require_admin, work_view
from radar_common.import_queue import enqueue
from radar_common.telemetry import correlation_id
from sqlalchemy.orm import Session
from strawberry.types import Info


@strawberry.type
class Mutation:
    @strawberry.mutation
    async def request_security_import(
        self,
        info: Info,
        request_key: UUID,
        release_id: strawberry.ID,
        name: str,
        version: str,
        observed_at: datetime,
    ) -> SourceImportJob:
        require_admin(info)
        UUID(str(release_id))
        if len(name) > 200 or len(version) > 200 or observed_at.tzinfo is None:
            raise ValueError("Invalid security import input")
        name = str(canonicalize_name(name, validate=True))
        canonicalize_version(Version(version))
        payload = {
            "release": str(release_id),
            "name": name,
            "version": version,
            "observed": observed_at.isoformat(),
        }
        correlation = correlation_id.get()

        def create() -> SourceImportJob:
            with Session(engine()) as session, session.begin():
                return work_view(enqueue(session, request_key, payload, correlation))

        return await db_call(create)
