from fastapi import FastAPI, Response
from prometheus_client import CONTENT_TYPE_LATEST, CollectorRegistry, Gauge, generate_latest
from sqlalchemy import text

from radar_common.database import engine


def install_metrics(app: FastAPI, counts: dict[str, str] | None = None) -> None:
    # Scrape only the owner's aggregates, in a synchronous FastAPI worker thread.
    @app.get("/metrics", include_in_schema=False)
    def metrics() -> Response:
        registry = CollectorRegistry()

        def gauge(name: str, value: float) -> None:
            Gauge("radar_" + name, name, registry=registry).set(value)

        with engine().connect() as conn:
            queue = conn.execute(
                text("""
                SELECT count(*) FILTER (WHERE status='queued') AS jobs,
                    extract(epoch from now()-min(created_at)
                        FILTER (WHERE status='queued')) AS age,
                    sum(greatest(attempts-1,0)) AS retries,
                    count(*) FILTER (WHERE status='failed') AS failed FROM source_work
            """)
            ).one()
            gauge("queued_jobs", queue.jobs)
            gauge("oldest_job_seconds", float(queue.age or 0))
            gauge("retry_attempts", queue.retries or 0)
            gauge("failed_jobs", queue.failed)
            state = conn.execute(
                text("""
                SELECT extract(epoch from max(last_success_at)) AS latest,
                    count(last_success_at) AS checked,
                    count(*) FILTER (WHERE last_success_at > now()-interval '1 day') AS fresh
                FROM source_state
            """)
            ).one()
            gauge("last_source_success_timestamp_seconds", float(state.latest or 0))
            gauge("checked_entities", state.checked)
            gauge("fresh_entities", state.fresh)
            gauge(
                "quota_requests",
                conn.scalar(
                    text("""
                SELECT coalesce(sum(used),0) FROM source_quota
                WHERE window_at > now()-interval '1 hour'
            """)
                )
                or 0,
            )
            for name, query in (counts or {}).items():
                gauge(name, conn.scalar(text(query)) or 0)
        return Response(generate_latest(registry), headers={"Content-Type": CONTENT_TYPE_LATEST})
