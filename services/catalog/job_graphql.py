import asyncio
import hmac
import logging
import os
from datetime import datetime
from uuid import UUID

import strawberry
from graphql import GraphQLError
from radar_common.telemetry import correlation_id
from sqlalchemy.exc import SQLAlchemyError
from strawberry.types import Info

from services.catalog.jobs import create_job, read_job
from services.catalog.models import Job


def require_dev_admin(info: Info) -> None:
    request = info.context.get("request")
    expected = os.getenv("DEV_ADMIN_TOKEN", "")
    supplied = request.headers.get("x-dev-admin-token", "") if request else ""
    if not expected or not hmac.compare_digest(supplied, expected):
        raise GraphQLError(
            "Development administrator token required", extensions={"code": "FORBIDDEN"}
        )


@strawberry.type
class ProbeJob:
    id: UUID
    status: str
    created_at: datetime
    completed_at: datetime | None
    correlation_id: str


def view(job: Job) -> ProbeJob:
    return ProbeJob(
        id=job.id,
        status=job.status,
        created_at=job.created_at,
        completed_at=job.completed_at,
        correlation_id=job.correlation_id,
    )


async def request_probe_job(info: Info, request_key: UUID) -> ProbeJob:
    require_dev_admin(info)
    try:
        job = await asyncio.to_thread(create_job, request_key, correlation_id.get())
    except SQLAlchemyError as error:
        logging.getLogger("radar.jobs").error(
            "job_storage_unavailable", extra={"error_type": type(error).__name__}
        )
        raise GraphQLError("Job storage unavailable", extensions={"code": "UNAVAILABLE"}) from None
    return view(job)


async def probe_job(info: Info, id: UUID) -> ProbeJob | None:
    require_dev_admin(info)
    try:
        job = await asyncio.to_thread(read_job, id)
    except SQLAlchemyError as error:
        logging.getLogger("radar.jobs").error(
            "job_storage_unavailable", extra={"error_type": type(error).__name__}
        )
        raise GraphQLError("Job storage unavailable", extensions={"code": "UNAVAILABLE"}) from None
    return view(job) if job else None
