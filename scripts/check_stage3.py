"""Deterministic PostgreSQL import checks. Run with Beat/import workers stopped."""

import json
import os
from datetime import UTC, datetime, timedelta
from unittest.mock import patch
from uuid import UUID, uuid4

import httpx
from radar_common.database import engine
from radar_common.import_queue import SourceState, Work, enqueue, record_state
from radar_common.source_http import SourceError, SourceHTTP
from sqlalchemy import delete, func, select, text
from sqlalchemy.orm import Session

from scripts.check_stage2 import gql
from services.catalog.domain_models import DependencyRow, ImportJobRow, PackageRow
from services.catalog.import_jobs import create_import
from services.catalog.normalization import package_id, release_id
from services.import_tasks import dispatch_due, run_work
from services.repositories.models import PackageRepositoryRow, RepositoryRow
from services.security.models import FindingRow, VersionScanRow, VulnerabilityRow

NAME = "radar-import-check-" + uuid4().hex[:12]
REPOSITORY = "radar-check/" + NAME
ADVISORY = "TEST-" + uuid4().hex
ALIAS = "TEST-ALIAS-" + uuid4().hex
REPO_ID = str(int(uuid4().hex[:12], 16))
STAMP = datetime.now(UTC)
CREATED: dict[str, list[UUID]] = {"catalog": [], "repositories": [], "security": []}
PARENTS: list[UUID] = []


def owner(name: str) -> None:
    engine.cache_clear()
    os.environ["SERVICE_NAME"] = name
    os.environ["DB_PASSWORD"] = os.environ[name.upper() + "_DB_PASSWORD"]


def response(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    if request.url.host == "pypi.org":
        return httpx.Response(
            200,
            json={
                "info": {
                    "name": NAME,
                    "version": "1.0",
                    "summary": "Synthetic import check",
                    "requires_python": ">=3.10",
                    "requires_dist": ['dep[ssl]>=1; python_version < "3.13"'],
                    "project_urls": {"Source": "https://github.com/" + REPOSITORY},
                }
            },
        )
    if request.url.host == "api.github.com":
        return httpx.Response(
            200,
            json={
                "id": int(REPO_ID),
                "full_name": REPOSITORY,
                "description": "Repository metadata fixture.",
                "private": False,
                "html_url": "https://github.com/" + REPOSITORY,
                "stargazers_count": 17,
            },
        )
    if path == "/v1/querybatch":
        query = json.loads(request.content)["queries"][0]
        assert query["package"]["name"] == NAME and query["version"] == "1.0"
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "vulns": [
                            {"id": ADVISORY, "modified": STAMP.isoformat()},
                            {"id": ALIAS, "modified": STAMP.isoformat()},
                        ]
                    }
                ]
            },
        )
    identity = path.split("/")[-1]
    return httpx.Response(
        200,
        json={
            "id": identity,
            "aliases": [ALIAS if identity == ADVISORY else ADVISORY],
            "summary": "Synthetic advisory",
            "affected": [
                {
                    "package": {"name": NAME, "ecosystem": "PyPI"},
                    "ranges": [
                        {"type": "ECOSYSTEM", "events": [{"introduced": "0"}, {"fixed": "1.2"}]}
                    ],
                }
            ],
            "modified": STAMP.isoformat(),
        },
    )


def fake_http(source: str, **kwargs: object) -> SourceHTTP:
    return SourceHTTP(source, transport=httpx.MockTransport(response), sleep=lambda _: None)


def make(payload: dict, *, when: datetime = STAMP) -> UUID:
    identity = uuid4()
    with Session(engine()) as session, session.begin():
        row = enqueue(session, identity, payload, "stage3-check")
        row.created_at = when
    CREATED[os.environ["SERVICE_NAME"]].append(identity)
    return identity


def work_state(identity: UUID) -> Work:
    with Session(engine()) as session:
        row = session.get(Work, identity)
        assert row
        return row


def ready_again(identity: UUID) -> None:
    with Session(engine()) as session, session.begin():
        row = session.get(Work, identity)
        assert row
        row.status, row.next_at, row.published_at = "queued", datetime.now(UTC), None


def check_catalog() -> None:
    owner("catalog")
    key = uuid4()
    row = create_import(key, [{"name": NAME, "version": "1.0"}], "stage3-check")
    PARENTS.append(row.id)
    assert create_import(key, [{"name": NAME, "version": "1.0"}], "stage3-check").id == row.id
    with Session(engine()) as session:
        identity = session.scalar(select(Work.id).where(Work.parent_id == row.id))
        assert identity
    CREATED["catalog"].append(identity)
    with patch(
        "services.catalog.importer.remote", side_effect=SourceError("ENRICHMENT_UNAVAILABLE", 30)
    ):
        run_work(identity)
    work = work_state(identity)
    assert work.status == "queued" and work.checkpoint["version"] == "1.0"
    assert work.attempts == 1 and work.error_code == "ENRICHMENT_UNAVAILABLE"
    ready_again(identity)
    # Recovery must reuse saved checkpoint, even if PyPI is now unavailable.
    with (
        patch(
            "services.catalog.importer.fetch", side_effect=AssertionError("Refetched checkpoint")
        ),
        patch("services.catalog.importer.remote"),
    ):
        run_work(identity)
        run_work(identity)  # Delivery after commit, before ack: no second side effect.
    assert work_state(identity).status == "succeeded"
    with Session(engine()) as session:
        parent = session.get(ImportJobRow, row.id)
        assert parent and parent.processed == 1
        assert (
            session.scalar(
                select(func.count())
                .select_from(PackageRow)
                .where(PackageRow.id == package_id(NAME))
            )
            == 1
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(DependencyRow)
                .where(DependencyRow.release_id == release_id(NAME, "1"))
            )
            == 1
        )
        package = session.get(PackageRow, package_id(NAME))
        assert package and package.requires_python == ">=3.10"
    # Older worker failure cannot override successful state.
    with Session(engine()) as session, session.begin():
        assert not record_state(session, package_id(NAME), STAMP - timedelta(days=1), "OLD")
    orphan = make({"name": NAME, "version": "1.0"})
    with patch("services.import_tasks.celery_app.send_task", side_effect=OSError("offline")):
        try:
            dispatch_due()
        except OSError:
            pass
        else:
            raise AssertionError("Broker outage not surfaced")
    assert work_state(orphan).published_at is None
    with patch("services.import_tasks.celery_app.send_task") as send:
        assert dispatch_due() >= 1
        assert send.called
    # Recovery also handles a published message lost before worker commit.
    with Session(engine()) as session, session.begin():
        orphan_work = session.get(Work, orphan)
        assert orphan_work
        orphan_work.published_at = STAMP - timedelta(minutes=10)
    with patch("services.import_tasks.celery_app.send_task") as send:
        assert dispatch_due() >= 1 and send.called


def check_repository() -> None:
    owner("repositories")
    payload = {
        "package": package_id(NAME),
        "urls": ["https://github.com/" + REPOSITORY],
        "observed": STAMP.isoformat(),
    }
    first = make(payload)
    # Stage 4: crash after repository commit, before Catalog projection publication.
    with patch(
        "services.repositories.importer.publish_projection",
        side_effect=SourceError("PROJECTION_UNAVAILABLE", 30),
    ):
        run_work(first)
    pending = work_state(first)
    assert pending.status == "queued" and pending.checkpoint["stars"] == 17
    with Session(engine()) as session, session.begin():
        work = session.get(Work, first)
        state = session.get(SourceState, package_id(NAME))
        assert work and state and state.status == "SUCCESS"
        work.next_at = STAMP
    with patch(
        "services.repositories.importer.fetch",
        side_effect=AssertionError("Must replay checkpoint without GitHub"),
    ):
        run_work(first)
    assert work_state(first).status == "succeeded"
    assert (
        gql(
            "query Check($id: ID!) { package(id: $id) { starProjection { stars } } }",
            {"id": package_id(NAME)},
        )["data"]["package"]["starProjection"]["stars"]
        == 17
    )
    run_work(first)
    second = make(payload)
    run_work(second)
    with Session(engine()) as session:
        repository = session.get(RepositoryRow, "github:" + REPO_ID)
        assert repository and repository.stars == 17
        assert repository.description == "Repository metadata fixture."
        assert (
            session.scalar(
                select(func.count())
                .select_from(PackageRepositoryRow)
                .where(PackageRepositoryRow.package_id == package_id(NAME))
            )
            == 1
        )
    # Refresh failures retain previously valid repository data.
    failing = make({**payload, "observed": (STAMP + timedelta(seconds=1)).isoformat()})
    with patch("services.repositories.importer.fetch", side_effect=SourceError("AUTH_REJECTED")):
        run_work(failing)
    assert work_state(failing).status == "failed"
    with Session(engine()) as session:
        state = session.get(SourceState, package_id(NAME))
        repository = session.get(RepositoryRow, "github:" + REPO_ID)
        assert state and state.status == "STALE"
        assert repository and repository.stars == 17


def check_security() -> None:
    owner("security")
    release = str(release_id(NAME, "1.0"))
    payload = {"release": release, "name": NAME, "version": "1.0", "observed": STAMP.isoformat()}
    identity = make(payload)
    run_work(identity)
    run_work(identity)
    repeat = make(payload)
    run_work(repeat)
    with Session(engine()) as session:
        scan = session.scalar(select(VersionScanRow).where(VersionScanRow.release_id == release))
        assert scan and scan.status == "SUCCESS" and scan.last_success_at
        assert (
            session.scalar(
                select(func.count()).select_from(FindingRow).where(FindingRow.scan_id == scan.id)
            )
            == 1
        ), "Aliases must not inflate findings"
        assert (
            session.scalar(select(FindingRow.fixed_version).where(FindingRow.scan_id == scan.id))
            == "1.2"
        )
    # Failure retains findings; it must never become a successful empty scan.
    failed = make({**payload, "observed": (STAMP + timedelta(seconds=1)).isoformat()})
    with patch("services.security.importer.fetch", side_effect=SourceError("INVALID_JSON")):
        run_work(failed)
    with Session(engine()) as session:
        scan = session.scalar(select(VersionScanRow).where(VersionScanRow.release_id == release))
        assert scan and scan.status == "STALE" and scan.last_success_at
        assert (
            session.scalar(
                select(func.count()).select_from(FindingRow).where(FindingRow.scan_id == scan.id)
            )
            == 1
        )
    # An older empty result must not erase newer findings.
    old = make({**payload, "observed": (STAMP - timedelta(days=1)).isoformat()})
    with patch("services.security.importer.fetch", return_value=[]):
        run_work(old)
    with Session(engine()) as session:
        scan = session.scalar(select(VersionScanRow).where(VersionScanRow.release_id == release))
        assert scan and scan.status == "STALE"
        assert (
            session.scalar(
                select(func.count()).select_from(FindingRow).where(FindingRow.scan_id == scan.id)
            )
            == 1
        )


def cleanup() -> None:
    for service in CREATED:
        owner(service)
        with Session(engine()) as session, session.begin():
            session.execute(delete(Work).where(Work.id.in_(CREATED[service])))
            session.execute(
                delete(SourceState).where(
                    SourceState.key.in_(
                        [
                            package_id(NAME),
                            str(release_id(NAME, "1")),
                            "github:" + REPO_ID,
                            "repository:github:" + REPO_ID,
                        ]
                    )
                )
            )
            if service == "catalog":
                session.execute(delete(ImportJobRow).where(ImportJobRow.id.in_(PARENTS)))
                session.execute(delete(PackageRow).where(PackageRow.id == package_id(NAME)))
            elif service == "repositories":
                session.execute(
                    delete(PackageRepositoryRow).where(
                        PackageRepositoryRow.package_id == package_id(NAME)
                    )
                )
                session.execute(
                    delete(RepositoryRow).where(RepositoryRow.id == "github:" + REPO_ID)
                )
            else:
                session.execute(
                    delete(VersionScanRow).where(
                        VersionScanRow.release_id == str(release_id(NAME, "1"))
                    )
                )
                session.execute(
                    delete(VulnerabilityRow).where(VulnerabilityRow.id.in_([ADVISORY, ALIAS]))
                )


def main() -> None:
    # No credential -> no queue writes, including downstream enqueue operations.
    denied = gql(
        """mutation { requestImport(requestKey: "00000000-0000-0000-0000-000000000001",
        targets: [{name: "example"}]) { id } }""",
        errors=True,
    )
    assert denied["errors"][0]["extensions"]["code"] == "FORBIDDEN"
    try:
        with patch("services.import_tasks.SourceHTTP", side_effect=fake_http):
            check_catalog()
            check_repository()
            check_security()
        owner("catalog")
        # The actual Beat owns the lock when running; a second connection cannot steal it.
        with engine().connect() as first, engine().connect() as second:
            assert first.scalar(text("SELECT pg_try_advisory_lock(72163004)"))
            assert not second.scalar(text("SELECT pg_try_advisory_lock(72163004)"))
            first.execute(text("SELECT pg_advisory_unlock(72163004)"))
        print("PASS: source checkpoints, duplicates, stale writes, aliases, outbox, permissions")
    finally:
        cleanup()


if __name__ == "__main__":
    main()
