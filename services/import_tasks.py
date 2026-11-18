"""Durable dispatch/recovery shared by three separately credentialed worker processes."""

import logging
import os
from datetime import UTC, datetime, timedelta
from importlib import import_module
from uuid import UUID

from celery.exceptions import SoftTimeLimitExceeded
from opentelemetry import trace
from pydantic import ValidationError
from radar_common.database import engine
from radar_common.import_queue import Work, quota_acquire, quota_block
from radar_common.source_http import SourceError, SourceHTTP
from radar_common.telemetry import correlation_id
from radar_common.tracing import span, trace_headers
from sqlalchemy import or_, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from services.catalog.celery_app import celery_app

logger = logging.getLogger("radar.import")
OWNERS = {"catalog": "pypi", "repositories": "github", "security": "osv"}


def dispatch_due() -> int:
    owner = os.environ["SERVICE_NAME"]
    if owner == "catalog":
        from services.catalog.domain_models import ImportJobRow
        from services.catalog.import_jobs import refresh_parent

        with Session(engine()) as session:
            parents = list(
                session.scalars(
                    select(ImportJobRow.id)
                    .where(ImportJobRow.status.in_(["queued", "running"]))
                    .limit(100)
                )
            )
        for parent in parents:
            refresh_parent(parent)
    now = datetime.now(UTC)
    count = 0
    with Session(engine()) as session, session.begin():
        rows = session.scalars(
            select(Work)
            .where(
                Work.status == "queued",
                Work.next_at <= now,
                or_(Work.published_at.is_(None), Work.published_at < now - timedelta(minutes=2)),
            )
            .order_by(Work.next_at)
            .limit(20)
            .with_for_update(skip_locked=True)
        )
        for row in rows:
            with span(owner + "-worker", "messaging.publish", row.traceparent):
                celery_app.send_task(
                    owner + ".import",
                    args=[str(row.id)],
                    queue=owner + ".imports",
                    routing_key=owner + ".imports",
                    headers={"x-request-id": row.correlation_id, **trace_headers()},
                    retry=False,
                    confirm_timeout=3,
                )
            row.published_at = now
            count += 1
    return count


def run_work(identity: UUID) -> None:
    owner = os.environ["SERVICE_NAME"]
    source = OWNERS[owner]
    handler = import_module("services." + owner + ".importer")
    # Session lock survives checkpoint transactions; a killed connection releases it.
    with engine().connect() as lock:
        acquired = lock.scalar(
            text("SELECT pg_try_advisory_lock(hashtextextended(:id,0))"), {"id": str(identity)}
        )
        lock.commit()
        if not acquired:
            return
        try:
            with Session(engine(), expire_on_commit=False) as session, session.begin():
                work = session.get(Work, identity)
                if not work or work.status != "queued" or work.next_at > datetime.now(UTC):
                    return
                work.attempts += 1
                work.next_at = datetime.now(UTC) + timedelta(minutes=2)
            token = correlation_id.set(work.correlation_id)
            http = SourceHTTP(
                source,
                token=os.getenv("GITHUB_TOKEN", ""),
                acquire=lambda: quota_acquire(source),
                block=lambda delay: quota_block(source, delay),
            )
            error: SourceError | None = None
            try:
                if work.attempts > 5:
                    raise SourceError("ATTEMPT_BUDGET")
                handler.process(work, http)
            except SourceError as caught:
                error = caught
            except (ValidationError, ValueError):
                error = SourceError("INVALID_SCHEMA")
            except SQLAlchemyError:
                error = SourceError("DATABASE", 30)
            except SoftTimeLimitExceeded:
                error = SourceError("TASK_TIMEOUT", 30)
            finally:
                http.close()
                correlation_id.reset(token)
            with Session(engine()) as session, session.begin():
                row = session.get(Work, identity)
                assert row
                if error:
                    row.error_code = error.code
                    # Quota waits do not consume HTTP retries; jobs still have a 24-hour deadline.
                    if error.code == "LOCAL_QUOTA":
                        row.attempts -= 1
                    expired = datetime.now(UTC) - row.created_at > timedelta(days=1)
                    if error.retry_after is not None and row.attempts < 5 and not expired:
                        row.next_at = datetime.now(UTC) + timedelta(
                            seconds=max(1, error.retry_after)
                        )
                        row.published_at = None
                    else:
                        row.status = "failed"
                    handler.failed(session, work, error.code)
                else:
                    row.status, row.error_code = "succeeded", None
            if owner == "catalog":
                from services.catalog.import_jobs import refresh_parent

                refresh_parent(work.parent_id)
            if error:
                current_span = trace.get_current_span()
                current_span.set_status(trace.StatusCode.ERROR)
                current_span.set_attribute("radar.source.error", error.code)
            logger.info(
                "source_work_completed",
                extra={
                    "service": owner,
                    "job_id": str(identity),
                    "status": "deferred_or_failed" if error else "succeeded",
                    "error_type": error.code if error else None,
                    "correlation_id": work.correlation_id,
                },
            )
        finally:
            lock.execute(
                text("SELECT pg_advisory_unlock(hashtextextended(:id,0))"), {"id": str(identity)}
            )
            lock.commit()


def consume_work(identity: str) -> None:
    run_work(UUID(identity))


@celery_app.task(name="catalog.refresh-follows", soft_time_limit=25, time_limit=30)
def refresh_follows() -> int:
    from services.catalog.follow_refresh import schedule

    return schedule()


@celery_app.task(name="catalog.reconcile-projection", soft_time_limit=25, time_limit=30)
def reconcile_projection() -> int:
    from services.catalog.projection import reconcile

    return reconcile()


for _owner in OWNERS:
    # Routing and process credentials limit each consumer to its own queue and DB.
    celery_app.task(name=_owner + ".import", soft_time_limit=240, time_limit=270)(consume_work)
    celery_app.task(name=_owner + ".dispatch")(dispatch_due)
