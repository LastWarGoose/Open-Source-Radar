"""Service-local durable work/outbox and source freshness; no domain models."""

import os
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import DateTime, Integer, String, func, select, text
from sqlalchemy.dialects.postgresql import JSONB, insert
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from radar_common.database import engine
from radar_common.source_http import SourceError
from radar_common.tracing import trace_headers


class QueueBase(DeclarativeBase):
    pass


class Work(QueueBase):
    __tablename__ = "source_work"
    id: Mapped[UUID] = mapped_column(primary_key=True)
    parent_id: Mapped[UUID | None] = mapped_column(index=True)
    payload: Mapped[dict] = mapped_column(JSONB)
    checkpoint: Mapped[dict] = mapped_column(JSONB, default=dict)
    status: Mapped[str] = mapped_column(String(16), default="queued")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    error_code: Mapped[str | None] = mapped_column(String(64))
    correlation_id: Mapped[str] = mapped_column(String(64))
    traceparent: Mapped[str | None] = mapped_column(String(55))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    next_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SourceState(QueueBase):
    __tablename__ = "source_state"
    key: Mapped[str] = mapped_column(String(250), primary_key=True)
    status: Mapped[str] = mapped_column(String(16))
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(64))


class Quota(QueueBase):
    __tablename__ = "source_quota"
    source: Mapped[str] = mapped_column(String(16), primary_key=True)
    window_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used: Mapped[int] = mapped_column(Integer)
    next_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


def enqueue(
    session: Session, identity: UUID, payload: dict, correlation: str, parent: UUID | None = None
) -> Work:
    session.execute(
        insert(Work)
        .values(
            id=identity,
            payload=payload,
            parent_id=parent,
            correlation_id=correlation,
            traceparent=trace_headers().get("traceparent"),
            status="queued",
            attempts=0,
            checkpoint={},
        )
        .on_conflict_do_nothing()
    )
    row = session.get(Work, identity)
    if row is None:
        raise RuntimeError("Missing work")
    if row.payload != payload:
        raise ValueError("Idempotency key already used with different input")
    return row


def source_budget(source: str) -> tuple[int, float]:
    limits = {"pypi": (120, 0.5), "github": (30, 1.0), "osv": (300, 0.2)}
    limit, interval = limits[source]
    prefix = "RADAR_" + source.upper()
    limit = int(os.getenv(prefix + "_REQUESTS_PER_HOUR", str(limit)))
    interval = float(os.getenv(prefix + "_MIN_INTERVAL", str(interval)))
    ceiling = {"pypi": 6000, "github": 30, "osv": 6000}[source]
    if not 1 <= limit <= ceiling or not limits[source][1] <= interval <= 60:
        raise ValueError("Invalid source request budget")
    return limit, interval


def quota_acquire(source: str) -> None:
    now = datetime.now(UTC)
    limit, interval = source_budget(source)
    with Session(engine()) as session, session.begin():
        session.execute(
            insert(Quota)
            .values(
                source=source,
                window_at=now,
                used=0,
                next_at=now,
            )
            .on_conflict_do_nothing()
        )
        row = session.scalar(select(Quota).where(Quota.source == source).with_for_update())
        assert row
        if row.next_at > now:
            raise SourceError("LOCAL_QUOTA", (row.next_at - now).total_seconds())
        if (now - row.window_at).total_seconds() >= 3600:
            row.window_at, row.used = now, 0
        if row.used >= limit:
            raise SourceError("LOCAL_QUOTA", max(1, 3600 - (now - row.window_at).total_seconds()))
        row.used += 1
        row.next_at = now + timedelta(seconds=interval)


def quota_block(source: str, seconds: float) -> None:
    with Session(engine()) as session, session.begin():
        session.execute(
            text("UPDATE source_quota SET next_at=greatest(next_at,:until) WHERE source=:source"),
            {"source": source, "until": datetime.now(UTC) + timedelta(seconds=seconds)},
        )


def record_state(session: Session, key: str, observed: datetime, error: str | None = None) -> bool:
    session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"), {"key": "source:" + key}
    )
    row = session.get(SourceState, key)
    if row and row.observed_at > observed:
        return False
    now = datetime.now(UTC)
    if row is None:
        row = SourceState(key=key, status="UNKNOWN", observed_at=observed, checked_at=now)
        session.add(row)
    row.observed_at, row.checked_at, row.error_code = observed, now, error
    row.status = ("STALE" if row.last_success_at else "FAILED") if error else "SUCCESS"
    if not error:
        row.last_success_at = now
    session.flush()
    return True
