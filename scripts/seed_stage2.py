"""Explicit synthetic seed, never an external import. Writes each owner's own database."""

from datetime import UTC, datetime
from uuid import NAMESPACE_URL, UUID, uuid5

from radar_common.database import database_url
from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from services.catalog.normalization import package_id, release_id
from services.catalog.store import save_package, save_release, save_requirement
from services.repositories.models import PackageRepositoryRow, RepositoryRow
from services.repositories.normalization import github_name
from services.security.models import FindingRow, VersionScanRow
from services.security.store import save_advisory
from services.workspace.access import DEV_ACTORS
from services.workspace.models import ActorRow, CollectionItemRow, CollectionRow, NotificationRow

STAMP = datetime(2026, 11, 17, tzinfo=UTC)
BULK_NAMES = [f"radar-fixture-{i:03d}" for i in range(105)]
VERSIONS = ["1.0rc1", "1.0", "1.9", "1.10", "2.0a1", "2.0", "3.0"]


def stable_id(value: str) -> UUID:
    return uuid5(NAMESPACE_URL, "radar-stage2:" + value)


def seed_catalog() -> None:
    db = create_engine(database_url("catalog"), hide_parameters=True)
    try:
        with Session(db) as session, session.begin():
            for name in ["fastapi", "strawberry-graphql", "shared-lib", *BULK_NAMES]:
                save_package(
                    session,
                    name,
                    "Synthetic API fixture for stage 2",
                    STAMP,
                    source="SYNTHETIC",
                    license="MIT",
                )
                versions = VERSIONS if name == "fastapi" else ["1.0"]
                for version in versions:
                    identity = save_release(
                        session, name, version, STAMP, source="SYNTHETIC", yanked=version == "1.9"
                    )
                    if name != "shared-lib":
                        save_requirement(
                            session, identity, 'shared_lib[fast]>=1.0; python_version >= "3.10"'
                        )
    finally:
        db.dispose()


def seed_repositories() -> None:
    db = create_engine(database_url("repositories"), hide_parameters=True)
    try:
        with Session(db) as session, session.begin():
            for url in (
                "https://github.com/example/radar-shared",
                "https://github.com/example/radar-extra",
            ):
                name = github_name(url)
                identity = "github:" + name
                session.execute(
                    insert(RepositoryRow)
                    .values(
                        id=identity,
                        full_name=name,
                        url=url,
                        stars=42,
                        source="SYNTHETIC",
                        source_id=identity,
                        fetched_at=STAMP,
                    )
                    .on_conflict_do_nothing()
                )
                for package in ["fastapi", "strawberry-graphql", *BULK_NAMES]:
                    session.execute(
                        insert(PackageRepositoryRow)
                        .values(
                            package_id=package_id(package),
                            repository_id=identity,
                            status="UNVERIFIED",
                        )
                        .on_conflict_do_nothing()
                    )
    finally:
        db.dispose()


def seed_security() -> None:
    db = create_engine(database_url("security"), hide_parameters=True)
    try:
        with Session(db) as session, session.begin():
            advisory = save_advisory(
                session,
                "RADAR-DEMO-001",
                ["RADAR-ALIAS-001"],
                "Synthetic advisory, not a real vulnerability report",
                STAMP,
                source="SYNTHETIC",
            )
            states = [
                ("fastapi", "1.0", "SUCCESS"),
                ("fastapi", "1.9", "SUCCESS"),
                ("fastapi", "1.10", "FAILED"),
                ("fastapi", "2.0a1", "UNKNOWN"),
                ("fastapi", "2.0", "STALE"),
                *[(name, "1.0", "SUCCESS") for name in BULK_NAMES],
            ]
            for name, version, status in states:
                target = str(release_id(name, version))
                identity = stable_id("scan:" + target)
                session.execute(
                    insert(VersionScanRow)
                    .values(
                        id=identity,
                        release_id=target,
                        status=status,
                        source="SYNTHETIC",
                        checked_at=STAMP if status != "UNKNOWN" else None,
                        last_success_at=STAMP if status in ("SUCCESS", "STALE") else None,
                        error_code="FIXTURE_UNAVAILABLE" if status == "FAILED" else None,
                    )
                    .on_conflict_do_nothing()
                )
                if name == "fastapi" and version == "1.0":
                    session.execute(
                        insert(FindingRow)
                        .values(scan_id=identity, vulnerability_id=advisory)
                        .on_conflict_do_nothing()
                    )
    finally:
        db.dispose()


def seed_workspace() -> None:
    db = create_engine(database_url("workspace"), hide_parameters=True)
    try:
        with Session(db) as session, session.begin():
            for owner in DEV_ACTORS:
                session.execute(insert(ActorRow).values(id=owner).on_conflict_do_nothing())
                identity = stable_id("collection:" + str(owner))
                session.execute(
                    insert(CollectionRow)
                    .values(
                        id=identity,
                        owner_id=owner,
                        name="Stage 2 synthetic collection",
                        created_at=STAMP,
                    )
                    .on_conflict_do_nothing()
                )
                for package in ("fastapi", "strawberry-graphql"):
                    session.execute(
                        insert(CollectionItemRow)
                        .values(collection_id=identity, package_id=package_id(package))
                        .on_conflict_do_nothing()
                    )
                if owner == DEV_ACTORS[1]:
                    session.execute(
                        insert(CollectionItemRow)
                        .values(collection_id=identity, package_id="pypi:radar-missing-reference")
                        .on_conflict_do_nothing()
                    )
                session.execute(
                    insert(NotificationRow)
                    .values(
                        id=stable_id("notification:" + str(owner)),
                        owner_id=owner,
                        message="Synthetic stage 2 notification",
                        package_id=package_id("fastapi"),
                        created_at=STAMP,
                    )
                    .on_conflict_do_nothing()
                )
    finally:
        db.dispose()


def main() -> None:
    for seed in (seed_catalog, seed_repositories, seed_security, seed_workspace):
        seed()
        print("Seed complete: " + seed.__name__, flush=True)


if __name__ == "__main__":
    main()
