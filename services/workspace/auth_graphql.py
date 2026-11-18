import os
from concurrent.futures import ThreadPoolExecutor

import strawberry
from radar_common.graphql import db_call, db_call_on
from radar_common.session import COOKIE, require_origin
from strawberry.types import Info

from services.workspace import accounts
from services.workspace.models import AccountRow

# Password work must not occupy the threads used by session reads and collections.
password_pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="workspace-auth")


@strawberry.type
class Account:
    id: strawberry.ID
    username: str
    role: str


def account_view(row: AccountRow) -> Account:
    return Account(id=strawberry.ID(str(row.actor_id)), username=row.username, role=row.role)


@strawberry.type
class Registration:
    account: Account
    recovery_code: str


def cookie(info: Info, value: str) -> None:
    response = info.context["response"]
    response.headers["cache-control"] = "no-store, private"
    response.set_cookie(
        COOKIE,
        value,
        httponly=True,
        samesite="strict",
        secure=os.getenv("SITE_URL", "").startswith("https://"),
        max_age=accounts.SESSION_SECONDS if value else 0,
        path="/",
    )


def mutation_origin(info: Info) -> None:
    request = info.context["request"]
    require_origin(request)
    if request.scope["type"] != "http" or request.method != "POST":
        raise accounts.fail("POST required", "FORBIDDEN")


@strawberry.type
class AuthQuery:
    @strawberry.field
    async def me(self, info: Info) -> Account | None:
        return info.context["account"]


@strawberry.type
class AuthMutation:
    @strawberry.mutation
    async def register(self, info: Info, username: str, password: str) -> Registration:
        mutation_origin(info)
        row, token, recovery = await db_call_on(
            password_pool, accounts.register, username, password
        )
        cookie(info, token)
        return Registration(account=account_view(row), recovery_code=recovery)

    @strawberry.mutation
    async def login(self, info: Info, username: str, password: str) -> Account:
        mutation_origin(info)
        row, token = await db_call_on(password_pool, accounts.login, username, password)
        cookie(info, token)
        return account_view(row)

    @strawberry.mutation
    async def logout(self, info: Info) -> bool:
        mutation_origin(info)
        await db_call(accounts.logout, info.context["request"].cookies.get(COOKIE, ""))
        cookie(info, "")
        return True

    @strawberry.mutation
    async def recover_account(
        self, info: Info, username: str, recovery_code: str, password: str
    ) -> str:
        mutation_origin(info)
        code = await db_call_on(password_pool, accounts.recover, username, recovery_code, password)
        cookie(info, "")
        return code
