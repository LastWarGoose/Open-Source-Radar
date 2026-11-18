import asyncio
from collections.abc import AsyncGenerator
from uuid import UUID

from strawberry.types import Info

from services.catalog.domain_graphql import ImportJob
from services.catalog.import_jobs import import_job


async def import_progress(info: Info, job_id: UUID) -> AsyncGenerator[ImportJob, None]:
    """Read durable state immediately, then revalidate session on every tick."""
    previous = None
    while True:
        job = await import_job(info, job_id)
        if job is None:
            raise ValueError("Unknown import")
        signature = (job.status, job.processed, job.error_code, job.completed_at)
        if signature != previous:
            yield job
            previous = signature
        if job.status in ("succeeded", "failed"):
            return
        await asyncio.sleep(1)
