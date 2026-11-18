from datetime import UTC, datetime
from uuid import UUID, uuid4

from radar_common.database import engine
from radar_common.tracing import trace_headers
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from services.catalog.models import Job, Outbox, ProbeReceipt


def create_job(request_key: UUID, request_id: str) -> Job:
    with Session(engine(), expire_on_commit=False) as session, session.begin():
        statement = (
            insert(Job)
            .values(
                id=uuid4(),
                request_key=request_key,
                status="queued",
                correlation_id=request_id,
                traceparent=trace_headers().get("traceparent"),
            )
            .on_conflict_do_nothing(index_elements=[Job.request_key])
            .returning(Job.id)
        )
        created_id = session.scalar(statement)
        if created_id is not None:
            session.add(Outbox(job_id=created_id))
        job = session.scalar(select(Job).where(Job.request_key == request_key))
        if job is None:
            raise RuntimeError("Job transaction did not produce a record")
        return job


def read_job(job_id: UUID) -> Job | None:
    with Session(engine()) as session:
        return session.get(Job, job_id)


def complete_probe(job_id: UUID) -> bool:
    """Receipt and completion commit together; duplicate delivery has no second effect."""
    with Session(engine()) as session, session.begin():
        job = session.scalar(select(Job).where(Job.id == job_id).with_for_update())
        if job is None:
            raise ValueError("Unknown job")
        if job.status == "succeeded":
            return False
        session.add(ProbeReceipt(job_id=job_id))
        job.status = "succeeded"
        job.completed_at = datetime.now(UTC)
        return True
