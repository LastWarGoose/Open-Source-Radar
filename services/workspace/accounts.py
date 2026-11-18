"""Opaque database sessions; passwords use pwdlib's Argon2 implementation."""

import hashlib
import hmac
import re
import secrets
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from graphql import GraphQLError
from pwdlib import PasswordHash
from radar_common.database import engine
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from services.workspace.models import AccountRow, ActorRow, AuthAttemptRow, SessionRow

PASSWORD = PasswordHash.recommended()
DUMMY = PASSWORD.hash(secrets.token_urlsafe(32))
AUTH_BUDGET = ("authentication:global", 300)
SESSION_SECONDS = 60 * 60 * 24 * 7


def fail(message: str, code: str = "BAD_USER_INPUT") -> GraphQLError:
    return GraphQLError(message, extensions={"code": code})


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def username_value(value: str) -> str:
    value = value.strip().lower()
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{2,39}", value):
        raise fail("Логин: 3–40 латинских букв, цифр, _ или -")
    return value


def password_value(value: str) -> str:
    if not 12 <= len(value) <= 128:
        raise fail("Пароль: от 12 до 128 символов")
    return value


def throttle(*budgets: tuple[str, int]) -> None:
    now = datetime.now(UTC)
    with Session(engine()) as session, session.begin():
        session.execute(delete(AuthAttemptRow).where(AuthAttemptRow.reset_at < now))
        for key, limit in budgets:
            used = session.scalar(
                insert(AuthAttemptRow)
                .values(key=digest(key), attempts=1, reset_at=now + timedelta(minutes=15))
                .on_conflict_do_update(
                    index_elements=[AuthAttemptRow.key],
                    set_={"attempts": AuthAttemptRow.attempts + 1},
                    where=AuthAttemptRow.attempts < limit,
                )
                .returning(AuthAttemptRow.attempts)
            )
            if used is None:
                break
        else:
            return
    # Commit any earlier debit even when a later budget is exhausted.
    raise fail("Слишком много попыток. Повторите через 15 минут", "RATE_LIMITED")


def principal(token: str) -> AccountRow | None:
    if not token or len(token) > 128:
        return None
    with Session(engine()) as session:
        return session.scalar(
            select(AccountRow)
            .join(SessionRow)
            .where(
                SessionRow.token_hash == digest(token), SessionRow.expires_at > datetime.now(UTC)
            )
        )


def issue(session: Session, actor: UUID) -> str:
    token = secrets.token_urlsafe(32)
    session.execute(delete(SessionRow).where(SessionRow.expires_at < datetime.now(UTC)))
    session.add(
        SessionRow(
            token_hash=digest(token),
            actor_id=actor,
            expires_at=datetime.now(UTC) + timedelta(seconds=SESSION_SECONDS),
        )
    )
    return token


def register(username: str, password: str) -> tuple[AccountRow, str, str]:
    username = username_value(username)
    password_value(password)
    throttle(("register:global", 50))
    hashed = PASSWORD.hash(password)
    recovery = secrets.token_urlsafe(32)
    with Session(engine(), expire_on_commit=False) as session, session.begin():
        # Serialize registration of a name without leaving orphan actors on a race.
        from sqlalchemy import text

        session.execute(text("SELECT pg_advisory_xact_lock(hashtext(:name))"), {"name": username})
        if session.scalar(select(AccountRow).where(AccountRow.username == username)):
            raise fail("Этот логин недоступен")
        identity = uuid4()
        session.add(ActorRow(id=identity))
        session.flush()
        account = AccountRow(
            actor_id=identity,
            username=username,
            password_hash=hashed,
            recovery_hash=digest(recovery),
            role="user",
        )
        session.add(account)
        session.flush()
        return account, issue(session, identity), recovery


def login(username: str, password: str) -> tuple[AccountRow, str]:
    username = username_value(username)
    if len(password) > 128:
        raise fail("Неверный логин или пароль", "UNAUTHENTICATED")
    throttle(("login:" + username, 10), AUTH_BUDGET)
    with Session(engine()) as session:
        credentials = session.execute(
            select(AccountRow.actor_id, AccountRow.password_hash).where(
                AccountRow.username == username
            )
        ).one_or_none()
    valid = PASSWORD.verify(password, credentials.password_hash if credentials else DUMMY)
    if not valid or credentials is None:
        raise fail("Неверный логин или пароль", "UNAUTHENTICATED")
    with Session(engine(), expire_on_commit=False) as session, session.begin():
        # Recovery can replace the hash while Argon2 is running. Serialize only session issuance.
        row = session.scalar(
            select(AccountRow)
            .where(
                AccountRow.actor_id == credentials.actor_id,
                AccountRow.password_hash == credentials.password_hash,
            )
            .with_for_update()
        )
        if row is None:
            raise fail("Неверный логин или пароль", "UNAUTHENTICATED")
        return row, issue(session, row.actor_id)


def recover(username: str, code: str, password: str) -> str:
    username = username_value(username)
    password_value(password)
    throttle(("recovery:" + username, 10), AUTH_BUDGET)
    if len(code) > 128:
        raise fail("Неверный логин или код восстановления", "UNAUTHENTICATED")
    hashed = PASSWORD.hash(password)
    recovery = secrets.token_urlsafe(32)
    with Session(engine()) as session, session.begin():
        row = session.scalar(
            select(AccountRow).where(AccountRow.username == username).with_for_update()
        )
        if row is None or not hmac.compare_digest(row.recovery_hash, digest(code)):
            raise fail("Неверный логин или код восстановления", "UNAUTHENTICATED")
        row.password_hash = hashed
        row.recovery_hash = digest(recovery)
        session.execute(delete(SessionRow).where(SessionRow.actor_id == row.actor_id))
    return recovery


def logout(token: str) -> None:
    with Session(engine()) as session, session.begin():
        session.execute(delete(SessionRow).where(SessionRow.token_hash == digest(token)))
