import logging
import signal
import threading
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import FrameType

from kombu.exceptions import OperationalError as BrokerError
from radar_common.database import engine
from radar_common.telemetry import configure_logging
from radar_common.tracing import span, trace_headers
from sqlalchemy import select
from sqlalchemy.exc import OperationalError as DatabaseError
from sqlalchemy.orm import Session

from services.catalog.celery_app import celery_app
from services.catalog.models import Job, Outbox

logger = logging.getLogger("radar.dispatcher")
HEARTBEAT = Path("/tmp/radar-dispatcher-heartbeat")


def dispatch_one() -> bool:
    with Session(engine()) as session, session.begin():
        row = session.scalar(
            select(Outbox)
            .where(
                Outbox.published_at.is_(None),
                Outbox.next_attempt_at <= datetime.now(UTC),
            )
            .order_by(Outbox.next_attempt_at, Outbox.job_id)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if row is None:
            return False
        job = session.get(Job, row.job_id)
        if job is None:
            raise RuntimeError("Outbox references a missing job")
        row.attempts += 1
        extra = {"service": "catalog", "job_id": str(job.id), "correlation_id": job.correlation_id}
        try:
            with span("catalog-dispatcher", "messaging.publish", job.traceparent):
                celery_app.send_task(
                    "catalog.probe",
                    args=[str(job.id)],
                    task_id=str(job.id),
                    headers={"x-request-id": job.correlation_id, **trace_headers()},
                    retry=False,
                    confirm_timeout=3,
                )
        except (BrokerError, OSError, TimeoutError) as error:
            row.next_attempt_at = datetime.now(UTC) + timedelta(
                seconds=min(2 ** min(row.attempts, 5), 30)
            )
            logger.warning(
                "publish_deferred",
                extra={**extra, "error_type": type(error).__name__, "attempts": row.attempts},
            )
        else:
            row.published_at = datetime.now(UTC)
            logger.info("job_published", extra=extra)
        return True


def main() -> None:
    configure_logging()
    stop = threading.Event()

    def request_stop(signum: int, frame: FrameType | None) -> None:
        stop.set()

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)
    while not stop.is_set():
        try:
            dispatched = dispatch_one()
        except DatabaseError as error:
            logger.warning(
                "database_unavailable",
                extra={"service": "catalog", "error_type": type(error).__name__},
            )
            dispatched = False
        HEARTBEAT.write_text(str(time.time()), encoding="ascii")
        stop.wait(0.1 if dispatched else 1)


if __name__ == "__main__":
    main()
