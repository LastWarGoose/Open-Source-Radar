"""Check stage-7 behavior in the restored disposable environment, without external traffic."""

import os
from datetime import UTC, datetime
from uuid import uuid4

import httpx
from radar_common.database import engine
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from scripts.check_stage3 import owner
from services.catalog.domain_models import ImportJobRow
from services.catalog.follow_refresh import schedule
from services.workspace.accounts import register
from services.workspace.models import FollowRow


def main() -> None:
    url = os.environ["GRAPHQL_URL"]
    query = """query Page($after:String) {
        packages(first:2, search:"fastapi", sort:RELEVANCE, after:$after,filter:{source:"PYPI"}) {
          nodes { id name releases(first:1){ nodes{version} } } pageInfo { endCursor }
        }
    }"""
    with httpx.Client(timeout=10) as client:

        def page(after: str | None) -> dict:
            body = client.post(url, json={"query": query, "variables": {"after": after}}).json()
            assert not body.get("errors")
            return dict(body["data"]["packages"])

        first = page(None)
        second = page(first["pageInfo"]["endCursor"])
        rows = first["nodes"] + second["nodes"]
        assert rows[0]["id"] == "pypi:fastapi" and len({row["id"] for row in rows}) == 4
        assert all(row["releases"]["nodes"] for row in rows)
        private = client.post(url, json={"query": "query Private{followedPackageBatch(first:2)}"})
        assert private.json()["errors"][0]["extensions"]["code"] == "FORBIDDEN"
    print("PASS relevance across cursors, batched releases and private follow aggregate")

    # Exactly two users follow the same real package in the restore drill.
    owner("workspace")
    for _ in range(2):
        account, _, _ = register("radar7-follow-" + uuid4().hex[:12], uuid4().hex)
        with Session(engine()) as session, session.begin():
            session.add(
                FollowRow(
                    owner_id=account.actor_id,
                    package_id="pypi:fastapi",
                    version="0",
                    observed_at=datetime.now(UTC),
                )
            )
    with Session(engine()) as session:
        previous = (
            session.scalar(
                select(func.max(FollowRow.package_id)).where(FollowRow.package_id < "pypi:fastapi")
            )
            or ""
        )
    owner("catalog")
    with Session(engine()) as session, session.begin():
        session.execute(
            text("UPDATE follow_refresh SET after_id=:previous,cycle_at=now(),next_at=now()"),
            {"previous": previous},
        )
        before = set(session.scalars(select(ImportJobRow.id)))
    assert 1 <= schedule() <= 2 and schedule() == 0
    with Session(engine()) as session:
        jobs = [row for row in session.scalars(select(ImportJobRow)) if row.id not in before]
        assert (
            sum(row.checkpoint["targets"] == [{"name": "fastapi", "version": None}] for row in jobs)
            == 1
        )
    print("PASS two follows produced one persisted refresh; repeated scheduler tick produced none")


if __name__ == "__main__":
    # Fixture creation is enabled explicitly in the disposable acceptance command.
    if os.getenv("RADAR_STAGE7_FIXTURES") != "1":
        raise SystemExit("Use the isolated stage-7 fixture command")
    main()
