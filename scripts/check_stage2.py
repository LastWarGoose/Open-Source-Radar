"""Real PostgreSQL + four-subgraph acceptance checks using only synthetic records."""

import argparse
import asyncio
import os
from importlib import import_module
from pathlib import Path
from uuid import uuid4

import httpx
from radar_common.database import database_url, engine
from sqlalchemy import create_engine, delete, event, func, select
from sqlalchemy.orm import DeclarativeBase, Session

from scripts.check_stage1 import check_databases
from scripts.seed_stage2 import BULK_NAMES, STAMP
from scripts.seed_stage2 import main as seed
from services.catalog.domain_models import DependencyRow, ImportJobRow, PackageRow, ReleaseRow
from services.catalog.normalization import package_id, release_id
from services.catalog.store import save_package, save_release, save_requirement
from services.repositories.models import PackageRepositoryRow, RepositoryRow
from services.security.models import AliasRow, FindingRow, VersionScanRow, VulnerabilityRow
from services.security.store import save_advisory
from services.workspace.access import DEV_ACTORS, dev_token
from services.workspace.models import CollectionItemRow, CollectionRow, NotificationRow

MODELS: dict[str, list[type[DeclarativeBase]]] = {
    "catalog": [PackageRow, ReleaseRow, DependencyRow],
    "repositories": [RepositoryRow, PackageRepositoryRow],
    "security": [VulnerabilityRow, AliasRow, VersionScanRow, FindingRow],
    "workspace": [CollectionRow, CollectionItemRow, NotificationRow],
}


def gql(
    query: str,
    variables: dict | None = None,
    actor: int | None = None,
    *,
    errors: bool = False,
    headers: dict | None = None,
) -> dict:
    supplied = dict(headers or {})
    if actor is not None:
        supplied["x-workspace-token"] = dev_token(os.environ["DEV_ADMIN_TOKEN"], DEV_ACTORS[actor])
    response = httpx.post(
        os.environ["GRAPHQL_URL"],
        json={"query": query, "variables": variables or {}},
        headers=supplied,
        timeout=20,
    )
    response.raise_for_status()
    result = response.json()
    if not errors:
        assert not result.get("errors"), result.get("errors")
    return result


def counts() -> dict[str, list[int]]:
    result = {}
    for service, models in MODELS.items():
        db = create_engine(database_url(service), hide_parameters=True)
        try:
            with Session(db) as session:
                result[service] = [
                    session.execute(select(func.count()).select_from(model)).scalar_one()
                    for model in models
                ]
        finally:
            db.dispose()
    return result


def uniqueness() -> None:
    db = create_engine(database_url("catalog"), hide_parameters=True)
    try:
        with Session(db) as session:
            key = "radar-check-" + uuid4().hex
            a = save_package(
                session, key.replace("-", "_").upper(), "fixture", STAMP, source="SYNTHETIC"
            )
            b = save_package(session, key.replace("-", "."), "fixture", STAMP, source="SYNTHETIC")
            assert a == b
            x = save_release(session, key, "1.0", STAMP, source="SYNTHETIC")
            y = save_release(session, key, "1.0.0", STAMP, source="SYNTHETIC")
            assert x == y
            dep = save_requirement(session, x, "shared-lib[fast]>=1; python_version >= '3.10'")
            assert dep == save_requirement(
                session, y, "shared-lib[fast]>=1; python_version >= '3.10'"
            )
            assert (
                session.scalar(
                    select(func.count()).select_from(PackageRow).where(PackageRow.id == a)
                )
                == 1
            )
            assert (
                session.scalar(
                    select(func.count()).select_from(ReleaseRow).where(ReleaseRow.package_id == a)
                )
                == 1
            )
            session.rollback()
    finally:
        db.dispose()
    db = create_engine(database_url("security"), hide_parameters=True)
    try:
        with Session(db) as session:
            suffix = uuid4().hex
            a = save_advisory(
                session,
                "TEST-A-" + suffix,
                ["TEST-ALIAS-" + suffix],
                "fixture",
                STAMP,
                source="SYNTHETIC",
            )
            b = save_advisory(
                session,
                "TEST-B-" + suffix,
                ["TEST-ALIAS-" + suffix],
                "fixture",
                STAMP,
                source="SYNTHETIC",
            )
            assert a == b
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(VulnerabilityRow)
                    .where(VulnerabilityRow.id.in_([a, b]))
                )
                == 1
            )
            session.rollback()
    finally:
        db.dispose()
    print("PASS: normalized name/version/requirement and advisory alias deduplication", flush=True)


def pagination() -> None:
    query = """query Catalog($first:Int!, $after:String, $sort:PackageSort!) {
      packages(first:$first, after:$after, search:"radar-fixture-", sort:$sort,
        filter:{license:"MIT", hasReleases:true}) {
        nodes { id name updatedAt } pageInfo { hasNextPage endCursor }
      }
    }"""
    for order in ("NAME_ASC", "UPDATED_DESC"):
        seen: list[str] = []
        cursor = None
        first_cursor = None
        while True:
            result = gql(query, {"first": 17, "after": cursor, "sort": order})["data"]["packages"]
            assert len(result["nodes"]) <= 17
            seen.extend(row["id"] for row in result["nodes"])
            cursor = result["pageInfo"]["endCursor"]
            first_cursor = first_cursor or cursor
            if not result["pageInfo"]["hasNextPage"]:
                break
        assert seen == [package_id(name) for name in BULK_NAMES]
        assert len(seen) == len(set(seen))
        assert (
            gql(query, {"first": 17, "after": cursor, "sort": order})["data"]["packages"]["nodes"]
            == []
        )
        other = "UPDATED_DESC" if order == "NAME_ASC" else "NAME_ASC"
        bad = gql(query, {"first": 17, "after": first_cursor, "sort": other}, errors=True)
        assert bad["errors"][0]["extensions"]["code"] == "BAD_USER_INPUT"
    assert (
        gql('query Empty { packages(search:"no-such-fixture-xyz") { nodes { id } } }')["data"][
            "packages"
        ]["nodes"]
        == []
    )
    for selection in ("packages(first:101)", "packages(first:0)", 'packages(after:"!")'):
        result = gql("query Bad { " + selection + " { nodes { id } } }", errors=True)
        assert result["errors"][0]["extensions"]["code"] == "BAD_USER_INPUT"
    result = gql(
        'query Limit { package(id:"pypi:fastapi") { releases(first:101) { nodes { id } } } }',
        errors=True,
    )
    assert result["errors"][0]["extensions"]["code"] == "BAD_USER_INPUT"
    fts = gql('query Search { packages(search:"Synthetic API") { nodes { source } } }')
    assert fts["data"]["packages"]["nodes"]
    print(
        "PASS: cursor traversal/ties/filters/search/empty/malformed/mismatched/oversize", flush=True
    )


def federation_and_access() -> None:
    query = (Path(__file__).resolve().parents[1] / "tests/fixtures/stage2.graphql").read_text(
        encoding="utf-8"
    )
    result = gql(query, actor=0)["data"]
    packages = result["myCollections"]["nodes"][0]["items"]["nodes"]
    first = next(row["package"] for row in packages if row["package"]["name"] == "fastapi")
    releases = first["releases"]["nodes"]
    assert [row["version"] for row in releases] == [
        "3.0",
        "2.0",
        "2.0a1",
        "1.10",
        "1.9",
        "1.0",
        "1.0rc1",
    ]
    by_version = {row["version"]: row for row in releases}
    assert by_version["3.0"]["scan"] is None
    assert by_version["2.0a1"]["scan"]["status"] == "UNKNOWN"
    assert by_version["1.10"]["scan"]["status"] == "FAILED"
    assert by_version["2.0"]["scan"]["status"] == "STALE"
    assert by_version["1.9"]["scan"]["status"] == "SUCCESS"
    assert by_version["1.9"]["scan"]["findings"]["nodes"] == []
    assert by_version["1.0"]["scan"]["findings"]["nodes"][0]["id"] == "RADAR-DEMO-001"
    assert by_version["1.9"]["yanked"] and by_version["2.0a1"]["isPrerelease"]
    dependency = by_version["1.0"]["dependencies"]["nodes"][0]
    assert dependency["package"]["name"] == "shared-lib" and dependency["extras"] == ["fast"]
    assert dependency["marker"] == 'python_version >= "3.10"'
    shared_ids = [
        {link["repository"]["id"] for link in row["package"]["repositories"]["nodes"]}
        for row in packages
    ]
    assert shared_ids[0] == shared_ids[1] and len(shared_ids[0]) == 2
    assert result["myNotifications"]["nodes"][0]["package"]["name"] == "fastapi"
    private_id = result["myCollections"]["nodes"][0]["id"]
    response_b = gql(
        "query MissingReference { myCollections { nodes { "
        "items { nodes { package { name } } } } } }",
        actor=1,
        errors=True,
    )
    assert response_b["errors"][0]["extensions"]["code"] == "NOT_FOUND"
    own_b = response_b["data"]["myCollections"]["nodes"][0]["items"]["nodes"]
    assert any(item["package"] is None for item in own_b)
    assert sum(item["package"] is not None for item in own_b) == 2
    assert (
        gql("query Private($id:ID!){ collection(id:$id){id} }", {"id": private_id}, actor=1)[
            "data"
        ]["collection"]
        is None
    )
    denied = gql(query, errors=True, headers={"x-user-id": str(DEV_ACTORS[0])})
    assert denied["errors"][0]["extensions"]["code"] == "UNAUTHENTICATED"
    assert (
        gql('query Missing { package(id:"pypi:no-such-package") { id } }')["data"]["package"]
        is None
    )
    print(
        "PASS: four-service nested graph, semantic versions/OSV states, "
        "shared repos, private ownership",
        flush=True,
    )


def nested_pages_and_jobs() -> None:
    query = (
        'query Releases($after:String){ package(id:"pypi:fastapi") { '
        "releases(first:2,after:$after){ nodes { version } "
        "pageInfo { hasNextPage endCursor } } } }"
    )
    versions: list[str] = []
    cursor = None
    while True:
        page = gql(query, {"after": cursor})["data"]["package"]["releases"]
        versions.extend(row["version"] for row in page["nodes"])
        cursor = page["pageInfo"]["endCursor"]
        if not page["pageInfo"]["hasNextPage"]:
            break
    assert versions == ["3.0", "2.0", "2.0a1", "1.10", "1.9", "1.0", "1.0rc1"]
    mismatch = gql(
        query.replace("pypi:fastapi", "pypi:strawberry-graphql"), {"after": cursor}, errors=True
    )
    assert mismatch["errors"][0]["extensions"]["code"] == "BAD_USER_INPUT"
    owned = (
        "query Own($after:String){ myCollections(first:1,after:$after){ pageInfo { endCursor } } }"
    )
    owned_cursor = gql(owned, actor=0)["data"]["myCollections"]["pageInfo"]["endCursor"]
    mismatch = gql(owned, {"after": owned_cursor}, actor=1, errors=True)
    assert mismatch["errors"][0]["extensions"]["code"] == "BAD_USER_INPUT"
    limits = [
        'query Limit { package(id:"pypi:fastapi") { '
        "repositories(first:101) { nodes { status } } } }",
        "query Limit { myCollections { nodes { items(first:101) { nodes { package { id } } } } } }",
        'query Limit { package(id:"pypi:fastapi") { releases { nodes { '
        "scan { findings(first:101) { nodes { id } } } } } } }",
    ]
    for query in limits:
        result = gql(query, actor=0, errors=True)
        assert result["errors"][0]["extensions"]["code"] == "BAD_USER_INPUT"

    query = "query Jobs { importJobs { nodes { id status source processed } } }"
    assert gql(query, errors=True)["errors"][0]["extensions"]["code"] == "FORBIDDEN"
    identity = uuid4()
    db = create_engine(database_url("catalog"), hide_parameters=True)
    try:
        with Session(db) as session, session.begin():
            session.add(
                ImportJobRow(
                    id=identity, request_key=uuid4(), status="queued", source="PYPI", processed=0
                )
            )
        rows = gql(query, headers={"x-dev-admin-token": os.environ["DEV_ADMIN_TOKEN"]})["data"][
            "importJobs"
        ]["nodes"]
        job = next(row for row in rows if row["id"] == str(identity))
        assert job["status"] == "queued" and job["processed"] == 0 and job["source"] == "PYPI"
    finally:
        with Session(db) as session, session.begin():
            session.execute(delete(ImportJobRow).where(ImportJobRow.id == identity))
        db.dispose()
    print(
        "PASS: nested cursor traversal/parent/owner boundaries/limits and ImportJob access",
        flush=True,
    )


async def batch_budget(service: str, size: int) -> int:
    os.environ["SERVICE_NAME"] = service
    os.environ["DB_PASSWORD"] = os.environ[service.upper() + "_DB_PASSWORD"]
    engine.cache_clear()
    db = engine()
    with db.connect() as connection:
        connection.exec_driver_sql("SELECT 1")
    count = 0

    def before(
        connection: object,
        cursor: object,
        statement: str,
        parameters: object,
        context: object,
        executemany: bool,
    ) -> None:
        nonlocal count
        if statement.lstrip().upper().startswith("SELECT"):
            count += 1

    event.listen(db, "before_cursor_execute", before)
    try:
        module = import_module("services." + service + ".app")
        domain = import_module("services." + service + ".domain_graphql")
        if service == "catalog":
            context = await domain.context_getter()
            query = """query Batch($first:Int!){ packages(first:$first,search:"radar-fixture-") {
              nodes { releases { nodes { dependencies { nodes { package { name } } } } } }
            } }"""
            variables: dict[str, object] = {"first": size}
        else:
            context = await domain.context_getter()
            typename = "Package" if service == "repositories" else "Release"
            keys = [
                package_id(name) if service == "repositories" else str(release_id(name, "1.0"))
                for name in BULK_NAMES[:size]
            ]
            fields = (
                "repositories { nodes { repository { fullName } } }"
                if service == "repositories"
                else "scan { status findings { nodes { id } } }"
            )
            query = (
                "query Batch($representations:[_Any!]!){ "
                "_entities(representations:$representations){ ... on "
                + typename
                + " { "
                + fields
                + " } } }"
            )
            variables = {"representations": [{"__typename": typename, "id": key} for key in keys]}
        result = await module.schema.execute(
            query, variable_values=variables, context_value=context
        )
        assert not result.errors, result.errors
        assert result.data
    finally:
        event.remove(db, "before_cursor_execute", before)
        db.dispose()
        engine.cache_clear()
    return count


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database-only", action="store_true")
    parser.add_argument("--partial", action="store_true")
    args = parser.parse_args()
    if args.partial:
        result = gql(
            'query Partial { package(id:"pypi:fastapi") { name '
            "repositories { nodes { repository { fullName } } } "
            "releases { nodes { version scan { status } } } } }",
            errors=True,
        )
        assert result.get("errors"), "Stopped Security should produce GraphQL errors"
        package = result["data"]["package"]
        assert package["name"] == "fastapi" and package["repositories"]["nodes"]
        assert package["releases"]["nodes"]
        assert all(row["scan"] is None for row in package["releases"]["nodes"])
        print("PASS: stopped Security leaves Catalog and Repositories data available", flush=True)
        return
    check_databases()
    seed()
    before = counts()
    seed()
    assert counts() == before, "Repeated seed changed row counts"
    uniqueness()
    if args.database_only:
        print("PASS: clean database migrations and repeated seed", flush=True)
        return
    pagination()
    federation_and_access()
    nested_pages_and_jobs()
    for service in ("catalog", "repositories", "security"):
        small = asyncio.run(batch_budget(service, 20))
        large = asyncio.run(batch_budget(service, 100))
        assert large == small and 0 < large <= 4, (service, small, large)
        print(f"PASS: {service} SQL budget, 20 parents={small}, 100 parents={large}", flush=True)
    print("PASS: stage 2 acceptance", flush=True)


if __name__ == "__main__":
    main()
