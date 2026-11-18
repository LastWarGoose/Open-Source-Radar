import logging
from uuid import UUID

from celery import Task
from radar_common.telemetry import correlation_id, task_headers
from sqlalchemy.exc import OperationalError

from services.catalog.celery_app import celery_app
from services.catalog.jobs import complete_probe

logger = logging.getLogger("radar.worker")


@celery_app.task(
    bind=True,
    name="catalog.probe",
    autoretry_for=(OperationalError,),
    retry_backoff=True,
    retry_backoff_max=30,
    retry_jitter=True,
    max_retries=5,
    soft_time_limit=15,
    time_limit=20,
)
def probe(self: Task, job_id: str) -> None:
    # Celery Task is dynamically supplied by the decorator.
    request = self.request
    token = correlation_id.set(task_headers(request.headers))
    try:
        changed = complete_probe(UUID(job_id))
        logger.info(
            "probe_completed" if changed else "duplicate_ignored",
            extra={
                "service": "catalog",
                "job_id": job_id,
                "status": "succeeded",
            },
        )
    finally:
        correlation_id.reset(token)
