"""Integration checks inside the private Compose network; no external API calls."""

import argparse
import concurrent.futures
import os
import time
from uuid import UUID, uuid4

import httpx
from radar_common.database import SERVICES, database_url, engine
from redis import Redis
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from services.catalog.celery_app import celery_app
from services.catalog.models import Job, Outbox, ProbeReceipt

FIELDS = "id status correlationId createdAt completedAt"


def graphql(query: str, variables: dict[str, str], *, authorized: bool = True) -> dict:
    headers = {"x-request-id": "stage1-" + variables.get("key", variables.get("id", "check"))}
    if authorized:
        headers["x-dev-admin-token"] = os.environ["DEV_ADMIN_TOKEN"]
    response = httpx.post(
        os.environ["GRAPHQL_URL"],
        json={
            "query": query,
            "variables": variables,
        },
        headers=headers,
        timeout=10,
    )
    response.raise_for_status()
    return response.json()


def enqueue(key: UUID) -> dict:
    result = graphql(
        "mutation Probe($key: UUID!) { requestProbeJob(requestKey: $key) { " + FIELDS + " } }",
        {"key": str(key)},
    )
    assert "errors" not in result, "Probe mutation returned GraphQL errors"
    return result["data"]["requestProbeJob"]


def get_job(job_id: str) -> dict:
    result = graphql(
        "query Job($id: UUID!) { probeJob(id: $id) { " + FIELDS + " } }", {"id": job_id}
    )
    assert "errors" not in result, "Job query returned GraphQL errors"
    assert result["data"]["probeJob"] is not None, "Job not found"
    return result["data"]["probeJob"]


def wait_success(job_id: str) -> None:
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        if get_job(job_id)["status"] == "succeeded":
            return
        time.sleep(0.25)
    raise AssertionError("Worker did not complete the job within 60 seconds")


def check_databases() -> None:
    for owner in SERVICES:
        url = database_url(owner)
        own_engine = create_engine(url, connect_args={"connect_timeout": 3})
        with own_engine.connect() as connection:
            assert connection.scalar(text("SELECT version_num FROM alembic_version")) == owner + (
                "_0003" if owner == "workspace" else "_0004" if owner == "security" else "_0005"
            )
            for target in (*SERVICES, "postgres"):
                allowed = connection.scalar(
                    text("SELECT has_database_privilege(current_user, :target, 'CONNECT')"),
                    {"target": target},
                )
                assert allowed == (target == owner)
        own_engine.dispose()
        for target in (*SERVICES, "postgres"):
            if target == owner:
                continue
            other_engine = create_engine(
                url.set(database=target), connect_args={"connect_timeout": 3}
            )
            try:
                with other_engine.connect():
                    raise AssertionError(f"Cross-database connection allowed: {owner} -> {target}")
            except OperationalError as error:
                # libpq connection failures do not expose SQLSTATE through psycopg.
                assert 'permission denied for database "' + target + '"' in str(error.orig), (
                    "Expected permission denial, not connection failure"
                )
            finally:
                other_engine.dispose()
    print("PASS: four migration heads and 16 cross-database access denials", flush=True)


def smoke() -> None:
    check_databases()
    mutation = "mutation Probe($key: UUID!) { requestProbeJob(requestKey: $key) { id } }"
    forbidden = graphql(mutation, {"key": str(uuid4())}, authorized=False)
    assert forbidden["errors"][0]["extensions"]["code"] == "FORBIDDEN"
    key = uuid4()
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        jobs = list(pool.map(lambda _: enqueue(key), range(12)))
    assert len({job["id"] for job in jobs}) == 1
    job_id = jobs[0]["id"]
    wait_success(job_id)
    assert get_job(job_id)["correlationId"] == "stage1-" + str(key)
    with Session(engine()) as session:
        assert (
            session.scalar(select(func.count()).select_from(Job).where(Job.request_key == key)) == 1
        )
        row = session.get(Outbox, UUID(job_id))
        assert row is not None and row.published_at is not None
        assert session.get(ProbeReceipt, UUID(job_id)) is not None
    # Duplicate persistent deliveries exercise the worker against the same committed receipt.
    for _ in range(2):
        celery_app.send_task("catalog.probe", args=[job_id], task_id=job_id, retry=False)
    cache = Redis(host="redis", socket_connect_timeout=3, socket_timeout=3)
    cache_key = "stage1-check:" + str(key)
    try:
        cache.set(cache_key, "ok", ex=60)
        assert cache.get(cache_key) == b"ok"
    finally:
        cache.delete(cache_key)
        cache.close()
    print(
        "PASS: forbidden mutation, concurrent idempotency, outbox delivery, "
        "completion, correlation ID, Redis",
        flush=True,
    )
    print(f"PROBE_JOB_ID={job_id}", flush=True)


def phase(action: str, key: UUID) -> None:
    if action == "enqueue":
        job = enqueue(key)
        assert job["status"] == "queued"
        print("PASS: mutation persists queued job while delivery is unavailable", flush=True)
        return
    with Session(engine()) as session:
        job = session.scalar(select(Job).where(Job.request_key == key))
        assert job is not None, "Saved job disappeared"
        job_id = str(job.id)
        row = session.get(Outbox, job.id)
        assert row is not None
        if action == "pending":
            assert job.status == "queued" and row.published_at is None and row.attempts > 0
        elif action == "published":
            deadline = time.monotonic() + 20
            while row.published_at is None and time.monotonic() < deadline:
                session.expire(row)
                time.sleep(0.25)
            assert row.published_at is not None and job.status == "queued"
    if action == "complete":
        wait_success(job_id)
        with Session(engine()) as session:
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(ProbeReceipt)
                    .where(ProbeReceipt.job_id == UUID(job_id))
                )
                == 1
            )
    print(f"PASS: {action} state verified in PostgreSQL", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--phase", choices=["smoke", "enqueue", "pending", "published", "complete"], default="smoke"
    )
    parser.add_argument("--key", type=UUID)
    args = parser.parse_args()
    if args.phase == "smoke":
        smoke()
    else:
        if args.key is None:
            parser.error("--key is required for phased checks")
        phase(args.phase, args.key)


if __name__ == "__main__":
    main()
