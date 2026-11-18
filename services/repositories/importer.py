import os
from datetime import UTC, datetime

import httpx
from radar_common.database import engine
from radar_common.import_queue import Work, record_state
from radar_common.source_http import SourceError, SourceHTTP
from radar_common.tracing import trace_headers
from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from services.repositories.models import PackageRepositoryRow, RepositoryRow
from services.repositories.source import candidates, fetch


def process(work: Work, http: SourceHTTP) -> None:
    if work.checkpoint:
        publish_projection(work.checkpoint)
        return
    fetched = datetime.now(UTC)
    records = []
    for name in candidates(work.payload["urls"])[: work.payload.get("max_repositories", 5)]:
        try:
            records.append(fetch(http, name))
        except SourceError as error:
            if error.code != "NOT_FOUND":
                raise
    with Session(engine()) as session, session.begin():
        if not record_state(
            session, work.payload["package"], datetime.fromisoformat(work.payload["observed"])
        ):
            return
        session.execute(
            delete(PackageRepositoryRow).where(
                PackageRepositoryRow.package_id == work.payload["package"]
            )
        )
        for record in records:
            # IDs from the provider remain stable across repository renames.
            identity = "github:" + str(record.id)
            if not record_state(
                session, "repository:" + identity, datetime.fromisoformat(work.payload["observed"])
            ):
                session.execute(
                    insert(PackageRepositoryRow)
                    .values(
                        package_id=work.payload["package"],
                        repository_id=identity,
                        status="VERIFIED",
                    )
                    .on_conflict_do_nothing()
                )
                continue
            values = dict(
                id=identity,
                full_name=record.full_name.lower(),
                description=(record.description or "").strip() or None,
                url=record.html_url,
                stars=record.stargazers_count,
                source="GITHUB",
                source_id=str(record.id),
                fetched_at=fetched,
            )
            session.execute(
                insert(RepositoryRow)
                .values(**values)
                .on_conflict_do_update(
                    index_elements=[RepositoryRow.id],
                    set_={k: v for k, v in values.items() if k != "id"},
                    where=RepositoryRow.fetched_at <= fetched,
                )
            )
            session.execute(
                insert(PackageRepositoryRow)
                .values(
                    package_id=work.payload["package"],
                    repository_id=identity,
                    status="VERIFIED",
                )
                .on_conflict_do_nothing()
            )
        from radar_common.import_queue import SourceState

        state = session.get(SourceState, work.payload["package"])
        assert state
        stars = session.scalar(
            select(func.max(RepositoryRow.stars))
            .join(PackageRepositoryRow)
            .where(
                PackageRepositoryRow.package_id == work.payload["package"],
                PackageRepositoryRow.status == "VERIFIED",
                RepositoryRow.source == "GITHUB",
            )
        )
        checkpoint = {
            "packageId": work.payload["package"],
            "stars": stars,
            "checkedAt": state.checked_at.isoformat(),
            "status": state.status,
        }
        row = session.get(Work, work.id)
        assert row
        row.checkpoint = checkpoint
    publish_projection(checkpoint)


def publish_projection(snapshot: dict) -> None:
    try:
        response = httpx.post(
            "http://catalog:8000/graphql",
            timeout=10,
            headers={"x-dev-admin-token": os.environ["DEV_ADMIN_TOKEN"], **trace_headers()},
            json={
                "query": """mutation Project($snapshot: RepositoryProjectionInput!) {
                    updateRepositoryProjection(snapshot: $snapshot)
                }""",
                "variables": {"snapshot": snapshot},
            },
        )
        response.raise_for_status()
        if response.json().get("errors"):
            raise SourceError("PROJECTION_UNAVAILABLE", 30)
    except (httpx.HTTPError, ValueError):
        raise SourceError("PROJECTION_UNAVAILABLE", 30) from None


def failed(session: Session, work: Work, code: str) -> None:
    current = session.get(Work, work.id)
    if current and current.checkpoint:
        return
    record_state(
        session, work.payload["package"], datetime.fromisoformat(work.payload["observed"]), code
    )
