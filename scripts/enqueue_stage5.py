"""Measure maximum campaign admission with consumers stopped; clean only owned test jobs."""

import json
import os
import statistics
import time
from pathlib import Path
from uuid import uuid4

import httpx
from radar_common.database import database_url
from radar_common.import_queue import Work
from sqlalchemy import create_engine, delete, func, select
from sqlalchemy.orm import Session

from scripts.run_stage5 import START
from services.catalog.domain_models import ImportJobRow


def main() -> None:
    manifest = json.loads(Path("/evidence/selection.json").read_text(encoding="utf-8"))
    samples = []
    database = create_engine(database_url("catalog"), hide_parameters=True)
    keys = []
    try:
        with httpx.Client(
            timeout=30, headers={"x-dev-admin-token": os.environ["DEV_ADMIN_TOKEN"]}
        ) as client:
            for _ in range(20):
                key = uuid4()
                keys.append(key)
                started = time.perf_counter()
                response = client.post(
                    os.environ["GRAPHQL_URL"],
                    json={
                        "query": START,
                        "variables": {"key": str(key), "names": manifest["names"], "target": 10000},
                    },
                )
                elapsed = (time.perf_counter() - started) * 1000
                assert response.status_code == 200 and not response.json().get("errors")
                state = response.json()["data"]["requestCampaign"]
                assert state["pending"] == 40 and state["succeeded"] == 0
                samples.append(elapsed)
    finally:
        with Session(database) as session, session.begin():
            identities = list(
                session.scalars(select(ImportJobRow.id).where(ImportJobRow.request_key.in_(keys)))
            )
            processed = session.scalar(
                select(func.count())
                .select_from(Work)
                .where(Work.parent_id.in_(identities), Work.status != "queued")
            )
            session.execute(delete(Work).where(Work.parent_id.in_(identities)))
            session.execute(delete(ImportJobRow).where(ImportJobRow.id.in_(identities)))
        database.dispose()
        assert processed == 0, "Consumers must be stopped during admission measurement"
    p95 = statistics.quantiles(samples, n=100, method="inclusive")[94]
    result = {
        "samples_ms": samples,
        "p95_ms": p95,
        "mean_ms": statistics.mean(samples),
        "passed": p95 <= 1000,
        "candidates_per_request": 15000,
        "queued_per_request": 40,
        "sample_count": 20,
        "external_source_requests": 0,
        "scope": "new campaign admission through gateway; jobs removed before consumers resume",
    }
    Path("/evidence/enqueue.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"Campaign admission: n=20, p95={p95:.1f} ms, threshold passed={p95 <= 1000}")
    assert p95 <= 1000


if __name__ == "__main__":
    main()
