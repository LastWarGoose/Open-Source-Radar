import os
from datetime import UTC, datetime
from uuid import uuid5

import httpx
from radar_common.database import engine
from radar_common.import_queue import Work, record_state
from radar_common.source_http import SourceError, SourceHTTP
from radar_common.telemetry import correlation_id
from radar_common.tracing import trace_headers
from sqlalchemy import delete
from sqlalchemy.orm import Session

from services.catalog.domain_models import DependencyRow, PackageRow
from services.catalog.normalization import package_id, release_id
from services.catalog.source import fetch
from services.catalog.store import save_package, save_release, save_requirement

REPOSITORY_MUTATION = """mutation EnrichRepository($key: UUID!, $package: ID!,
    $urls: [String!]!, $observed: DateTime!, $limit: Int!) {
  requestRepositoryImport(requestKey: $key, packageId: $package, urls: $urls,
    observedAt: $observed, maxRepositories: $limit) { id status }
}"""
SECURITY_MUTATION = """mutation EnrichSecurity($key: UUID!, $release: ID!, $name: String!,
    $version: String!, $observed: DateTime!) {
  requestSecurityImport(requestKey: $key, releaseId: $release, name: $name,
    version: $version, observedAt: $observed) { id status }
}"""


def remote(owner: str, query: str, variables: dict) -> None:
    try:
        result = httpx.post(
            "http://" + owner + ":8000/graphql",
            headers={
                "x-dev-admin-token": os.environ["DEV_ADMIN_TOKEN"],
                "x-request-id": correlation_id.get(),
                **trace_headers(),
            },
            json={"query": query, "variables": variables},
            timeout=10,
        )
        if result.status_code != 200 or result.json().get("errors"):
            raise SourceError("ENRICHMENT_UNAVAILABLE", 30)
    except (httpx.HTTPError, ValueError):
        raise SourceError("ENRICHMENT_UNAVAILABLE", 30) from None


def process(work: Work, http: SourceHTTP) -> None:
    name = work.payload["name"]
    checkpoint = work.checkpoint
    if not checkpoint:
        fetched = datetime.now(UTC)
        project, release = fetch(
            http,
            name,
            work.payload.get("version"),
            stable_only=work.payload.get("stable_only", False),
        )
        with Session(engine()) as session, session.begin():
            current = record_state(session, package_id(name), work.created_at)
            if current:
                identity = save_package(
                    session,
                    name,
                    project.summary or "",
                    fetched,
                    license=(project.license_expression or project.license or "")[:200] or None,
                )
                package = session.get(PackageRow, identity)
                assert package
                package.requires_python = project.requires_python
            release_identity = release_id(name, release.version)
            release_current = record_state(session, str(release_identity), work.created_at)
            if release_current:
                save_release(session, name, release.version, fetched, yanked=release.yanked)
                session.execute(
                    delete(DependencyRow).where(DependencyRow.release_id == release_identity)
                )
                for raw in release.requires_dist or []:
                    save_requirement(session, release_identity, raw)
            checkpoint = {
                "package": package_id(name),
                "release": str(release_identity),
                "name": name,
                "version": release.version,
                "urls": list((project.project_urls or {}).values())
                + ([project.home_page] if project.home_page else []),
                "observed": work.created_at.isoformat(),
                "historical": bool(work.payload.get("version")),
            }
            row = session.get(Work, work.id)
            assert row
            row.checkpoint = checkpoint
    if work.payload.get("repositories", True):
        remote(
            "repositories",
            REPOSITORY_MUTATION,
            {
                "key": str(uuid5(work.id, "github")),
                "package": checkpoint["package"],
                "urls": checkpoint["urls"],
                "observed": checkpoint["observed"],
                "limit": work.payload.get("repository_limit", 5),
            },
        )
    remote(
        "security",
        SECURITY_MUTATION,
        {
            "key": str(uuid5(work.id, "osv")),
            "release": checkpoint["release"],
            "name": checkpoint["name"],
            "version": checkpoint["version"],
            "observed": checkpoint["observed"],
        },
    )
    if not checkpoint["historical"]:
        remote(
            "workspace",
            """mutation NotifyPackage($id: ID!, $version: String!, $at: DateTime!) {
            recordPackageUpdate(packageId: $id, version: $version, observedAt: $at)
        }""",
            {
                "id": checkpoint["package"],
                "version": checkpoint["version"],
                "at": checkpoint["observed"],
            },
        )


def failed(session: Session, work: Work, code: str) -> None:
    # A failed cross-service enqueue must not claim that an already saved PyPI fetch failed.
    row = session.get(Work, work.id)
    if row and not row.checkpoint:
        record_state(session, package_id(work.payload["name"]), work.created_at, code)
