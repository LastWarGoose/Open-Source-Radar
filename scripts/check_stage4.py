"""Temporary, explicitly labelled public UI fixtures and projection acceptance checks.

PYPI/GITHUB/OSV identify simulated adapter output here, never live-source evidence.
Run only through verify_stage4: consumers stopped, fixtures removed in finally.
"""

import argparse
import os
from datetime import UTC, datetime, timedelta

from radar_common.database import engine
from radar_common.import_queue import SourceState, record_state
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from scripts.check_stage2 import gql
from scripts.check_stage3 import owner
from services.catalog.domain_models import PackageRow
from services.catalog.normalization import package_id, release_id
from services.catalog.projection import Snapshot, apply_snapshot, reconcile
from services.catalog.store import save_package, save_release, save_requirement
from services.repositories.models import PackageRepositoryRow, RepositoryRow
from services.security.models import AliasRow, FindingRow, VersionScanRow, VulnerabilityRow

NAMES = [
    "radar-stage4-" + suffix for suffix in ("alpha", "beta", "gamma", "delta", "epsilon", "hidden")
]
IDS = [package_id(name) for name in NAMES]
MARKER = "Synthetic stage 4 browser fixture — removed after verification"
ADVISORY = "TEST-RADAR-STAGE4"
STAMP = datetime.now(UTC) - timedelta(hours=1)


def reconcile_catalog() -> None:
    """Cover one full bounded cursor cycle, even when the fixture is beyond the first page."""
    with Session(engine()) as session:
        count = (
            session.scalar(
                select(func.count()).select_from(PackageRow).where(PackageRow.source == "PYPI")
            )
            or 0
        )
    # One extra batch handles an initial cursor past the current end of the catalog.
    for _ in range((count + 99) // 100 + 1):
        reconcile()


def seed() -> None:
    owner("catalog")
    with Session(engine()) as session, session.begin():
        assert not session.scalar(select(PackageRow.id).where(PackageRow.id.in_(IDS))), (
            "Fixture name collision; refusing overwrite"
        )
        for i, name in enumerate(NAMES):
            identity = save_package(
                session,
                name,
                MARKER,
                STAMP,
                source="SYNTHETIC" if i == 5 else "PYPI",
                license="MIT License" if i == 0 else "MIT" if i % 2 == 0 else "Apache-2.0",
            )
            record_state(session, identity, STAMP)
            if i == 1:
                record_state(session, identity, STAMP + timedelta(minutes=1), "TIMEOUT")
            if i == 4:
                continue
            for version in range(1, 22 if i == 0 else 2):
                release = save_release(session, name, f"{version}.0", STAMP)
                if i == 0 and version == 21:
                    for dep in range(25):
                        save_requirement(
                            session,
                            release,
                            f'radar-dep-{dep:02d}[ssl]>=1; python_version < "3.13"',
                        )
            if i == 0:
                save_release(session, name, "99.0", STAMP, source="SYNTHETIC")
            if i == 1:
                save_release(session, name, "1.1", STAMP)
    owner("repositories")
    with Session(engine()) as session, session.begin():
        for i, stars in enumerate([30, 50, 30, 0, None]):
            record_state(session, IDS[i], STAMP)
            if stars is not None:
                session.add(
                    RepositoryRow(
                        id=IDS[i],
                        full_name="radar-fixture/" + NAMES[i],
                        description=f"Source repository for {NAMES[i]}." if i == 0 else None,
                        url="https://github.com/radar-fixture/" + NAMES[i],
                        stars=stars,
                        source="GITHUB",
                        source_id=IDS[i],
                        fetched_at=STAMP,
                    )
                )
                session.flush()
                session.add(
                    PackageRepositoryRow(package_id=IDS[i], repository_id=IDS[i], status="VERIFIED")
                )
    owner("security")
    with Session(engine()) as session, session.begin():
        session.add(
            VulnerabilityRow(
                id=ADVISORY,
                summary="Synthetic advisory for browser verification",
                source="OSV",
                fetched_at=STAMP,
            )
        )
        session.flush()
        session.add(AliasRow(alias=ADVISORY + "-ALIAS", vulnerability_id=ADVISORY))
        for i, status in enumerate(["SUCCESS", "SUCCESS", "FAILED", "UNKNOWN"]):
            scan = VersionScanRow(
                release_id=str(release_id(NAMES[i], "21.0" if i == 0 else "1.0")),
                package_name=NAMES[i],
                version="21.0" if i == 0 else "1.0",
                status=status,
                source="OSV",
                checked_at=STAMP if i != 3 else None,
                last_success_at=(STAMP - timedelta(days=i)) if i < 2 else None,
                error_code="TIMEOUT" if i == 2 else None,
            )
            session.add(scan)
            session.flush()
            if i == 1:
                session.add(
                    FindingRow(scan_id=scan.id, vulnerability_id=ADVISORY, fixed_version="1.2")
                )
        older = VersionScanRow(
            release_id=str(release_id(NAMES[0], "1.0")),
            package_name=NAMES[0],
            version="1.0",
            status="STALE",
            source="OSV",
            checked_at=STAMP,
            last_success_at=STAMP - timedelta(days=1),
            error_code="TIMEOUT",
        )
        session.add(older)
        session.flush()
        session.add(FindingRow(scan_id=older.id, vulnerability_id=ADVISORY, fixed_version="2.1"))
    owner("catalog")
    reconcile_catalog()
    print("PASS: temporary UI fixture set ready", flush=True)


def checks() -> None:
    owner("catalog")
    license_query = "query LicenseState { catalogLicenseRevision catalogLicenses { nodes } }"
    original = gql(license_query)["data"]
    test_license = "LicenseRef-RadarStage4"
    with Session(engine()) as session, session.begin():
        row = session.get(PackageRow, IDS[0])
        assert row and row.license_key == "MIT"
        row.license_key = test_license
        session.flush()
        assert gql(license_query)["data"] == original, "Uncommitted license leaked"
    try:
        changed = gql(license_query)["data"]
        assert test_license in changed["catalogLicenses"]["nodes"]
        assert changed["catalogLicenseRevision"] != original["catalogLicenseRevision"]
    finally:
        with Session(engine()) as session, session.begin():
            row = session.get(PackageRow, IDS[0])
            assert row
            row.license_key = "MIT"
    restored = gql(license_query)["data"]
    assert restored["catalogLicenses"] == original["catalogLicenses"]
    assert restored["catalogLicenseRevision"] != changed["catalogLicenseRevision"]
    with Session(engine()) as session, session.begin():
        row = session.get(PackageRow, IDS[0])
        assert row and row.github_checked_at and row.github_stars == 30
        observed = row.github_checked_at
        projected = row.github_projected_at
        for timestamp in (observed, observed - timedelta(days=1)):
            assert not apply_snapshot(
                session,
                Snapshot(packageId=IDS[0], stars=999, checkedAt=timestamp, status="SUCCESS"),
            )
        session.refresh(row)
        assert row.github_stars == 30 and row.github_projected_at == projected
        row.github_checked_at = None
        row.github_stars = None
    reconcile_catalog()
    with Session(engine()) as session:
        row = session.get(PackageRow, IDS[0])
        assert row and row.github_stars == 30, "Reconciliation must repair missed publication"
    query = """query Check($after: String, $source: String!) {
      packages(first: 1, after: $after, search: "radar-stage4-",
               sort: STARS_DESC, filter: {source: $source}) {
        nodes { name starProjection { stars lagSeconds } }
        pageInfo { endCursor hasNextPage }
      }
    }"""
    cursor = None
    found = []
    for _ in range(10):
        page = gql(query, {"after": cursor, "source": "PYPI"})["data"]["packages"]
        found += [item["name"] for item in page["nodes"]]
        if not page["pageInfo"]["hasNextPage"]:
            break
        cursor = page["pageInfo"]["endCursor"]
    assert found == [NAMES[i] for i in (1, 0, 2, 3, 4)], found
    assert gql(query, {"after": cursor, "source": "SYNTHETIC"}, errors=True).get("errors"), (
        "Cursor must be bound to source filter"
    )
    detail = gql(
        """query Check($id: ID!) { package(id: $id) {
      releases(first: 100, source: "PYPI") { nodes { version source } }
      release(version: "99.0", source: "PYPI") { version }
    } }""",
        {"id": IDS[0]},
    )["data"]["package"]
    assert len(detail["releases"]["nodes"]) == 21 and detail["release"] is None
    # A shared repository may change without this package's SourceState changing.
    for stars in (31, 30):
        owner("repositories")
        with Session(engine()) as session, session.begin():
            repository = session.get(RepositoryRow, IDS[0])
            assert repository
            repository.stars = stars
            repository.fetched_at = datetime.now(UTC)
        owner("catalog")
        reconcile_catalog()
        with Session(engine()) as session:
            updated = session.get(PackageRow, IDS[0])
            assert updated and updated.github_stars == stars
    mutation = """mutation Check($snapshot: RepositoryProjectionInput!) {
      updateRepositoryProjection(snapshot: $snapshot)
    }"""
    variables = {
        "snapshot": {
            "packageId": IDS[0],
            "stars": 30,
            "checkedAt": observed.isoformat(),
            "status": "SUCCESS",
        }
    }
    assert gql(mutation, variables, errors=True).get("errors"), (
        "Projection mutation must be protected"
    )
    assert (
        gql(mutation, variables, headers={"x-dev-admin-token": os.environ["DEV_ADMIN_TOKEN"]})[
            "data"
        ]["updateRepositoryProjection"]
        is False
    )
    assert gql(
        'query Check { repositorySnapshots(packageIds: ["pypi:x"]) { stars } }', errors=True
    ).get("errors")
    print(
        "PASS: global stars order across 5 cursor pages, ties/zero/unknown; source scope; "
        "version isolation; duplicate/out-of-order updates; reconciliation; authorization",
        flush=True,
    )


def cleanup() -> None:
    owner("catalog")
    with Session(engine()) as session, session.begin():
        safe = list(
            session.scalars(
                select(PackageRow.id).where(PackageRow.id.in_(IDS), PackageRow.summary == MARKER)
            )
        )
        # Never remove a colliding package that was not created by this fixture.
        session.execute(delete(PackageRow).where(PackageRow.id.in_(safe)))
        session.execute(delete(SourceState).where(SourceState.key.in_(safe)))
    if not safe:
        return
    owner("repositories")
    with Session(engine()) as session, session.begin():
        session.execute(delete(RepositoryRow).where(RepositoryRow.id.in_(safe)))
        session.execute(delete(SourceState).where(SourceState.key.in_(safe)))
    owner("security")
    with Session(engine()) as session, session.begin():
        releases = [
            str(release_id(name, f"{v}.0"))
            for name in NAMES
            if package_id(name) in safe
            for v in range(1, 22)
        ]
        session.execute(delete(VersionScanRow).where(VersionScanRow.release_id.in_(releases)))
        session.execute(delete(VulnerabilityRow).where(VulnerabilityRow.id == ADVISORY))
    print("PASS: temporary fixture data removed", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=["seed", "check", "cleanup"])
    args = parser.parse_args()
    {"seed": seed, "check": checks, "cleanup": cleanup}[args.phase]()
