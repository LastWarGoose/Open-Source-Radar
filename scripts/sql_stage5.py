"""Real-data SQL counts, request cache isolation and query plans; administrative runner."""

import argparse
import asyncio
import json
import os
from copy import deepcopy
from datetime import UTC, datetime
from importlib import import_module
from pathlib import Path

from radar_common.database import engine
from sqlalchemy import event

from scripts.report_stage5 import read


async def measure(owner: str, keys: list[str], size: int) -> dict:
    os.environ["SERVICE_NAME"] = owner
    os.environ["DB_PASSWORD"] = os.environ[owner.upper() + "_DB_PASSWORD"]
    engine.cache_clear()
    database = engine()
    with database.connect() as connection:
        connection.exec_driver_sql("SELECT 1")
    statements: list[tuple[str, dict]] = []

    def before(
        connection: object,
        cursor: object,
        statement: str,
        parameters: dict,
        context: object,
        executemany: bool,
    ) -> None:
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append((statement, parameters))

    module = import_module("services." + owner + ".app")
    domain = import_module("services." + owner + ".domain_graphql")
    typename = "Release" if owner == "security" else "Package"
    fields = {
        "catalog": 'name releases(first:1,source:"PYPI") { nodes { '
        "dependencies(first:20) { nodes { name specifier marker extras } } } }",
        "repositories": "repositories(first:5) { nodes { repository { fullName stars } } }",
        "security": "scan { status findings(first:20) { nodes { id aliases(first:10) { "
        "nodes { name } } } } }",
    }[owner]
    query = (
        "query Batch($reps:[_Any!]!) { _entities(representations:$reps) { ... on "
        + typename
        + " { "
        + fields
        + " } } }"
    )
    variables = {"reps": [{"__typename": typename, "id": key} for key in keys[:size]]}
    event.listen(database, "before_cursor_execute", before)
    try:
        context = await domain.context_getter()
        result = await module.schema.execute(
            query, variable_values=deepcopy(variables), context_value=context
        )
        assert not result.errors and result.data
        count = len(statements)
        repeated = await module.schema.execute(
            query, variable_values=deepcopy(variables), context_value=context
        )
        assert not repeated.errors, [error.message for error in repeated.errors or []]
        cached = len(statements) - count
        fresh = await domain.context_getter()
        renewed = await module.schema.execute(
            query, variable_values=deepcopy(variables), context_value=fresh
        )
        assert not renewed.errors, [error.message for error in renewed.errors or []]
        isolated = len(statements) - count - cached
    finally:
        event.remove(database, "before_cursor_execute", before)
    plans = []
    if size == 100:
        with database.connect() as connection:
            for statement, parameters in statements[:count]:
                plan = connection.exec_driver_sql(
                    "EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + statement, parameters
                ).scalar_one()
                plans.append({"sql": statement, "plan": plan})
    database.dispose()
    engine.cache_clear()
    assert cached == 0 and isolated == count, (owner, count, cached, isolated)
    return {
        "parents": size,
        "selects": count,
        "same_request_repeat_selects": cached,
        "new_request_selects": isolated,
        "plans": plans,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="/evidence/sql.json")
    args = parser.parse_args()
    packages = [
        row["id"]
        for row in read(
            "catalog",
            """
        SELECT p.id FROM packages p WHERE p.source='PYPI'
        ORDER BY EXISTS(SELECT 1 FROM releases r JOIN dependency_requirements d
                        ON d.release_id=r.id WHERE r.package_id=p.id) DESC, p.name LIMIT 100""",
        )
    ]
    releases = [
        row["release_id"]
        for row in read(
            "security",
            """
        SELECT s.release_id FROM version_scans s WHERE s.source='OSV'
        ORDER BY EXISTS(SELECT 1 FROM scan_findings f WHERE f.scan_id=s.id) DESC,s.release_id
        LIMIT 100""",
        )
    ]
    linked = [
        row["package_id"]
        for row in read(
            "repositories",
            """
        SELECT DISTINCT p.package_id FROM package_repositories p
        JOIN repositories r ON r.id=p.repository_id WHERE r.source='GITHUB'
        ORDER BY p.package_id LIMIT 100""",
        )
    ]
    repository_keys = list(dict.fromkeys(linked + packages))[:100]
    result: dict = {"captured_at": datetime.now(UTC).isoformat(), "services": {}}
    for owner, keys in (
        ("catalog", packages),
        ("repositories", repository_keys),
        ("security", releases),
    ):
        assert len(keys) >= 100, (owner, len(keys))
        small = asyncio.run(measure(owner, keys, 20))
        large = asyncio.run(measure(owner, keys, 100))
        assert small["selects"] == large["selects"] and 0 < large["selects"] <= 5, (
            owner,
            small["selects"],
            large["selects"],
        )
        result["services"][owner] = {"20": small, "100": large, "keys": keys}
        print(f"{owner}: 20={small['selects']},100={large['selects']}; request cache isolated")
    result["catalog_plans"] = {}
    for name, clause in {
        "name": "source='PYPI' ORDER BY name,id",
        "updated": "source='PYPI' ORDER BY updated_at DESC,id",
        "stars": "source='PYPI' ORDER BY coalesce(github_stars,-1) DESC,id",
        "search": "source='PYPI' AND (name ILIKE '%python%' OR "
        "to_tsvector('simple',name || ' ' || summary) @@ "
        "websearch_to_tsquery('simple','python')) ORDER BY name,id",
        "license": "source='PYPI' AND license='MIT' ORDER BY name,id",
    }.items():
        result["catalog_plans"][name] = read(
            "catalog",
            "EXPLAIN (ANALYZE,BUFFERS,FORMAT JSON) SELECT * FROM packages WHERE "
            + clause
            + " LIMIT 21",
        )
    result["indexes"] = {
        owner: read(
            owner,
            """
        SELECT tablename,indexname,indexdef FROM pg_indexes
        WHERE schemaname='public' ORDER BY tablename,indexname""",
        )
        for owner in ("catalog", "repositories", "security", "workspace")
    }
    Path(args.output).write_text(json.dumps(result, indent=2, default=str) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
