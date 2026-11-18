import os
from datetime import UTC, datetime, timedelta
from uuid import NAMESPACE_URL, uuid5

import httpx
from radar_common.database import engine
from radar_common.telemetry import correlation_id
from radar_common.tracing import trace_headers
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from services.catalog.domain_models import PackageRow
from services.catalog.import_jobs import create_import


def schedule() -> int:
    # Each cycle refreshes each distinct real package once, including its GitHub discovery.
    now = datetime.now(UTC)
    with Session(engine()) as session, session.begin():
        row = session.execute(
            text(
                "SELECT after_id, cycle_at, next_at FROM follow_refresh "
                "WHERE id=1 FOR UPDATE SKIP LOCKED"
            )
        ).first()
        if row is None or row.next_at > now:
            return 0
        response = httpx.post(
            "http://workspace:8000/graphql",
            headers={"x-dev-admin-token": os.environ["DEV_ADMIN_TOKEN"], **trace_headers()},
            json={
                "query": "query RefreshFollows($after:String!) { "
                "followedPackageBatch(afterId:$after, first:2) }",
                "variables": {"after": row.after_id},
            },
            timeout=5,
        )
        response.raise_for_status()
        body = response.json()
        if body.get("errors"):
            raise RuntimeError("Workspace follow batch unavailable")
        ids = body["data"]["followedPackageBatch"]
        names = list(
            session.scalars(
                select(PackageRow.name).where(PackageRow.id.in_(ids), PackageRow.source == "PYPI")
            )
        )
        for name in names:
            key = uuid5(NAMESPACE_URL, f"follow-refresh/{row.cycle_at.isoformat()}/{name}")
            create_import(key, [{"name": name}], correlation_id.get() or key.hex)
        finished = len(ids) < 2
        completed_round = finished and bool(ids or row.after_id)
        next_at = now + (timedelta(days=1) if completed_round else timedelta(minutes=15))
        session.execute(
            text(
                "UPDATE follow_refresh SET after_id=:cursor, cycle_at=:cycle, next_at=:due "
                "WHERE id=1"
            ),
            {
                "cursor": "" if finished else ids[-1],
                "cycle": next_at if finished else row.cycle_at,
                "due": next_at,
            },
        )
        return len(names)
