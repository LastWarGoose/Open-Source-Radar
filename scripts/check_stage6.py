"""Isolated acceptance checks against real PostgreSQL and the federated gateway."""

import json
import os
import secrets
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from unittest.mock import patch
from uuid import UUID, uuid4

import httpx
from graphql import GraphQLError
from radar_common.database import engine
from radar_common.import_queue import Work
from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session
from websockets.sync.client import connect
from websockets.typing import Origin, Subprotocol

from scripts.check_stage3 import owner
from services.catalog.domain_models import ImportJobRow
from services.workspace import accounts
from services.workspace.accounts import digest
from services.workspace.models import (
    AccountRow,
    ActorRow,
    AuthAttemptRow,
    CollectionRow,
    FollowRow,
    NotificationRow,
    SessionRow,
)

URL = os.getenv("GRAPHQL_URL", "http://gateway:4000/graphql")
ORIGIN = "http://localhost:3000"
REGISTER = """mutation Register($u:String!,$p:String!) {
 register(username:$u,password:$p) { account { id role } recoveryCode }
}"""
LOGIN = """mutation Login($u:String!,$p:String!) { login(username:$u,password:$p) { id role } }"""
RECOVER = """mutation Recover($u:String!,$p:String!,$c:String!) {
 recoverAccount(username:$u,password:$p,recoveryCode:$c) }"""


def call(
    client: httpx.Client, query: str, variables: dict | None = None, *, error: bool = False
) -> dict:
    response = client.post(URL, json={"query": query, "variables": variables or {}})
    assert response.status_code == 200, response.status_code
    result = response.json()
    if error:
        assert result.get("errors"), "Expected access/input rejection"
    else:
        assert not result.get("errors"), [e["message"] for e in result.get("errors", [])]
    return result.get("data") or {}


def cleanup(names: list[str]) -> None:
    owner("workspace")
    with Session(engine()) as session, session.begin():
        ids = list(
            session.scalars(select(AccountRow.actor_id).where(AccountRow.username.in_(names)))
        )
        for model, column in (
            (SessionRow, SessionRow.actor_id),
            (FollowRow, FollowRow.owner_id),
            (NotificationRow, NotificationRow.owner_id),
            (CollectionRow, CollectionRow.owner_id),
            (AccountRow, AccountRow.actor_id),
            (ActorRow, ActorRow.id),
        ):
            session.execute(delete(model).where(column.in_(ids)))
        keys = [digest(kind + name) for name in names for kind in ("login:", "recovery:")]
        session.execute(delete(AuthAttemptRow).where(AuthAttemptRow.key.in_(keys)))


def check_concurrent_budget() -> None:
    key = "check-budget:" + uuid4().hex

    def reserve() -> bool:
        try:
            accounts.throttle((key, 3))
        except GraphQLError as exc:
            assert exc.extensions and exc.extensions.get("code") == "RATE_LIMITED"
            return False
        return True

    try:
        with ThreadPoolExecutor(max_workers=4) as pool:
            requests = [pool.submit(reserve) for _ in range(8)]
            assert sum(request.result() for request in requests) == 3
        with Session(engine()) as session, session.begin():
            session.execute(
                update(AuthAttemptRow)
                .where(AuthAttemptRow.key == digest(key))
                .values(reset_at=datetime.now(UTC) - timedelta(seconds=1))
            )
        assert reserve()
    finally:
        with Session(engine()) as session, session.begin():
            session.execute(delete(AuthAttemptRow).where(AuthAttemptRow.key == digest(key)))


def check_recovery_during_login(
    client: httpx.Client, username: str, password: str, reg: dict
) -> None:
    verify = accounts.PASSWORD.verify
    replacement = secrets.token_urlsafe(24)

    def verify_and_recover(candidate: str, stored: str) -> bool:
        valid = verify(candidate, stored)
        assert valid
        call(client, RECOVER, {"u": username, "p": replacement, "c": reg["recoveryCode"]})
        return valid

    with patch.object(accounts.PASSWORD, "verify", side_effect=verify_and_recover):
        try:
            accounts.login(username, password)
        except GraphQLError as exc:
            assert exc.extensions and exc.extensions.get("code") == "UNAUTHENTICATED"
        else:
            raise AssertionError("A superseded password issued a session")
    assert (
        call(client, LOGIN, {"u": username, "p": replacement})["login"]["id"]
        == reg["account"]["id"]
    )


def main() -> None:
    names = ["radar6-" + uuid4().hex[:16] for _ in range(2)]
    password = secrets.token_urlsafe(24)
    jobs: list[UUID] = []
    a = httpx.Client(headers={"origin": ORIGIN}, timeout=20)
    b = httpx.Client(headers={"origin": ORIGIN}, timeout=20)
    anon = httpx.Client(headers={"origin": ORIGIN}, timeout=20)
    try:
        ra = call(a, REGISTER, {"u": names[0], "p": password})["register"]
        rb = call(b, REGISTER, {"u": names[1], "p": password})["register"]
        assert ra["account"]["role"] == rb["account"]["role"] == "user"
        token = a.cookies.get("radar_session")
        assert token and token not in json.dumps(ra)
        cid = call(a, 'mutation { createCollection(name:"Stage 6 private") { id } }')[
            "createCollection"
        ]["id"]
        assert (
            call(b, "query C($id:ID!) { collection(id:$id) { id } }", {"id": cid})["collection"]
            is None
        )
        call(anon, "query { myCollections { nodes { id } } }", error=True)
        for mutation in (
            "mutation C($id:ID!) { deleteCollection(id:$id) }",
            "mutation C($id:ID!) {"
            ' addPackageToCollection(id:$id,packageId:"pypi:fastapi") { id } }',
            "mutation C($id:ID!) {"
            ' removePackageFromCollection(id:$id,packageId:"pypi:fastapi") { id } }',
        ):
            call(b, mutation, {"id": cid}, error=True)
        for _ in range(2):
            call(
                a,
                "mutation C($id:ID!) {"
                ' addPackageToCollection(id:$id,packageId:"pypi:fastapi") { id } }',
                {"id": cid},
            )
        items = call(
            a,
            "query C($id:ID!) { collection(id:$id) { items { nodes { package { name } } } } }",
            {"id": cid},
        )
        assert items["collection"]["items"]["nodes"] == [{"package": {"name": "fastapi"}}]
        a.headers["origin"] = "https://untrusted.invalid"
        call(a, 'mutation { createCollection(name:"CSRF") { id } }', error=True)
        call(a, LOGIN, {"u": names[0], "p": password}, error=True)
        a.headers["origin"] = ORIGIN
        for client in (a, b, anon):
            call(
                client,
                "mutation I($key:UUID!) {"
                ' requestImport(requestKey:$key,targets:[{name:"fastapi"}]) { id } }',
                {"key": str(uuid4())},
                error=True,
            )
        call(a, 'mutation { followPackage(packageId:"pypi:fastapi") }')
        owner("workspace")
        from services.workspace.personal import record_update

        stamp = datetime.now(UTC) + timedelta(seconds=1)
        for _ in range(2):
            record_update("pypi:fastapi", "9999.stage6", stamp)
        record_update("pypi:fastapi", "old", stamp - timedelta(days=1))
        notifications = call(a, "query { myNotifications { nodes { id message } } }")[
            "myNotifications"
        ]["nodes"]
        assert len(notifications) == 1
        nid = notifications[0]["id"]
        call(b, "mutation N($id:ID!) { markNotificationRead(id:$id) }", {"id": nid}, error=True)
        call(a, "mutation N($id:ID!) { markNotificationRead(id:$id) }", {"id": nid})
        assert (
            call(b, "query { myNotifications { nodes { id } } }")["myNotifications"]["nodes"] == []
        )
        with Session(engine()) as session, session.begin():
            session.execute(
                update(AccountRow)
                .where(AccountRow.actor_id == UUID(ra["account"]["id"]))
                .values(role="admin")
            )
        key = str(uuid4())
        create = (
            "mutation I($key:UUID!) {"
            ' requestImport(requestKey:$key,targets:[{name:"fastapi"}]) { id } }'
        )
        jid = call(a, create, {"key": key})["requestImport"]["id"]
        jobs.append(UUID(jid))
        assert call(a, create, {"key": key})["requestImport"]["id"] == jid
        wsurl = URL.replace("http://", "ws://").replace("https://", "wss://")
        payload = {
            "query": "subscription P($id:UUID!) {"
            " importProgress(jobId:$id) { id status processed } }",
            "variables": {"id": jid},
        }
        with connect(
            wsurl,
            origin=Origin(ORIGIN),
            additional_headers={"Cookie": "radar_session=" + token},
            subprotocols=[Subprotocol("graphql-transport-ws")],
        ) as ws:
            ws.send(json.dumps({"type": "connection_init"}))
            assert json.loads(ws.recv(timeout=10))["type"] == "connection_ack"
            ws.send(json.dumps({"id": "p", "type": "subscribe", "payload": payload}))
            first = json.loads(ws.recv(timeout=10))
            assert first.get("payload", {}).get("data"), first
            assert first["payload"]["data"]["importProgress"]["id"] == jid, first
            owner("catalog")
            with Session(engine()) as session, session.begin():
                session.execute(
                    update(ImportJobRow)
                    .where(ImportJobRow.id == UUID(jid))
                    .values(status="running", processed=1)
                )
            started = time.monotonic()
            changed = json.loads(ws.recv(timeout=10))
            assert changed["payload"]["data"]["importProgress"]["processed"] == 1
            print(f"Observed durable progress update after {time.monotonic() - started:.3f}s")
            call(a, "mutation { logout }")
            final = json.loads(ws.recv(timeout=10))
            assert final["type"] == "error" or final.get("payload", {}).get("errors"), final
        stale = httpx.Client(
            headers={"origin": ORIGIN, "cookie": "radar_session=" + token}, timeout=20
        )
        assert call(stale, "query { me { id } }")["me"] is None
        call(a, LOGIN, {"u": names[0], "p": password})
        with connect(
            wsurl,
            origin=Origin(ORIGIN),
            additional_headers={
                "Cookie": "radar_session=" + (a.cookies.get("radar_session") or "")
            },
            subprotocols=[Subprotocol("graphql-transport-ws")],
        ) as ws:
            ws.send(json.dumps({"type": "connection_init"}))
            ws.recv(timeout=10)
            ws.send(json.dumps({"id": "p", "type": "subscribe", "payload": payload}))
            assert json.loads(ws.recv(timeout=10))["payload"]["data"]["importProgress"]["id"] == jid
            owner("workspace")
            with Session(engine()) as session, session.begin():
                session.execute(
                    update(SessionRow)
                    .where(SessionRow.actor_id == UUID(ra["account"]["id"]))
                    .values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
                )
            expired = json.loads(ws.recv(timeout=10))
            assert expired["type"] == "error" or expired.get("payload", {}).get("errors"), expired
        newpassword = secrets.token_urlsafe(24)
        newcode = call(anon, RECOVER, {"u": names[0], "p": newpassword, "c": ra["recoveryCode"]})[
            "recoverAccount"
        ]
        assert newcode != ra["recoveryCode"] and call(a, "query { me { id } }")["me"] is None
        call(
            anon,
            RECOVER,
            {"u": names[0], "p": password, "c": ra["recoveryCode"]},
            error=True,
        )
        call(a, LOGIN, {"u": names[0], "p": password}, error=True)
        call(a, LOGIN, {"u": names[0], "p": newpassword})
        owner("workspace")
        with Session(engine()) as session, session.begin():
            session.execute(
                update(SessionRow)
                .where(SessionRow.actor_id == UUID(ra["account"]["id"]))
                .values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
            )
        call(a, "query { myCollections { nodes { id } } }", error=True)
        check_concurrent_budget()
        check_recovery_during_login(anon, names[1], password, rb)
        print(
            "PASS: registration, private CRUD, CSRF, user/admin, durable notifications, "
            "import idempotency, subscription reconnect/revocation, recovery rotation and expiry, "
            "concurrent attempt budget and password replacement during login"
        )
    finally:
        owner("catalog")
        with Session(engine()) as session, session.begin():
            session.execute(delete(Work).where(Work.parent_id.in_(jobs)))
            session.execute(delete(ImportJobRow).where(ImportJobRow.id.in_(jobs)))
        cleanup(names)
        for client in (a, b, anon):
            client.close()


if __name__ == "__main__":
    main()
