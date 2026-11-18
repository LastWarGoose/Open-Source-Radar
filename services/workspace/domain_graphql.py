from datetime import datetime
from uuid import UUID

import strawberry
from fastapi import Request
from radar_common.database import engine
from radar_common.graphql import (
    Connection,
    PageKey,
    connection,
    db_call,
    decode_cursor,
    encode_cursor,
    invalid,
    page_loader,
    page_size,
    scope_key,
)
from radar_common.session import COOKIE
from sqlalchemy import Select, select
from sqlalchemy.orm import Session
from strawberry.types import Info

from services.workspace.access import actor_for_token
from services.workspace.accounts import principal
from services.workspace.models import CollectionItemRow, CollectionRow, NotificationRow


def uuid_value(value: str) -> UUID:
    try:
        return UUID(value)
    except ValueError:
        raise invalid("Invalid UUID") from None


@strawberry.federation.type(
    keys=[
        strawberry.federation.schema_directives.Key(
            fields=strawberry.federation.schema_directives.FieldSet("id"), resolvable=False
        )
    ]
)
class Package:
    id: strawberry.ID


@strawberry.type
class CollectionItem:
    package_id: strawberry.Private[str]

    @strawberry.field
    def package(self) -> Package | None:
        return Package(id=strawberry.ID(self.package_id))


@strawberry.type
class Collection:
    id: strawberry.ID
    name: str
    created_at: datetime

    @strawberry.field
    async def items(
        self, info: Info, first: int = 20, after: str | None = None
    ) -> Connection[CollectionItem]:
        loaders = info.context["workspace"]
        owner = loaders.owner()
        scope = scope_key("items", str(owner), str(self.id))
        rows = await loaders.items.load(PageKey(str(self.id), page_size(first), after))
        return connection(
            [CollectionItem(package_id=row.package_id) for row in rows],
            first,
            lambda item: encode_cursor(scope, item.package_id),
        )


@strawberry.type
class Notification:
    id: strawberry.ID
    message: str
    created_at: datetime
    read_at: datetime | None
    target: strawberry.Private[str | None]

    @strawberry.field
    def package(self) -> Package | None:
        return Package(id=strawberry.ID(self.target)) if self.target else None


def collection_view(row: CollectionRow) -> Collection:
    return Collection(id=strawberry.ID(str(row.id)), name=row.name, created_at=row.created_at)


class WorkspaceLoaders:
    def __init__(self, token: str, actor: UUID | None = None) -> None:
        self.token = token
        self.actor = actor

        def items(key: PageKey) -> Select[CollectionItemRow]:
            owner = self.owner()
            statement = (
                select(CollectionItemRow)
                .join(CollectionRow)
                .where(
                    CollectionItemRow.collection_id == uuid_value(key.parent),
                    CollectionRow.owner_id == owner,
                )
            )
            cursor = decode_cursor(key.after, scope_key("items", str(owner), key.parent))
            if cursor:
                statement = statement.where(CollectionItemRow.package_id > cursor[0])
            return statement

        self.items = page_loader(CollectionItemRow, items, [CollectionItemRow.package_id])

    def owner(self) -> UUID:
        return self.actor if self.actor else actor_for_token(self.token)


async def context_getter(request: Request) -> dict:
    account = await db_call(principal, request.cookies.get(COOKIE, ""))
    return {
        "workspace": WorkspaceLoaders(
            request.headers.get("x-workspace-token", ""), account.actor_id if account else None
        )
    }


@strawberry.type
class Query:
    @strawberry.field
    async def collection(self, info: Info, id: strawberry.ID) -> Collection | None:
        owner = info.context["workspace"].owner()
        identity = uuid_value(str(id))

        def read() -> Collection | None:
            with Session(engine()) as session:
                row = session.scalar(
                    select(CollectionRow).where(
                        CollectionRow.id == identity, CollectionRow.owner_id == owner
                    )
                )
                return collection_view(row) if row else None

        return await db_call(read)

    @strawberry.field
    async def my_collections(
        self, info: Info, first: int = 20, after: str | None = None
    ) -> Connection[Collection]:
        owner = info.context["workspace"].owner()
        page_size(first)
        scope = scope_key("collections", str(owner))
        cursor = decode_cursor(after, scope)
        statement = (
            select(CollectionRow).where(CollectionRow.owner_id == owner).order_by(CollectionRow.id)
        )
        if cursor:
            statement = statement.where(CollectionRow.id > uuid_value(cursor[0]))

        def read() -> list[Collection]:
            with Session(engine()) as session:
                return [collection_view(row) for row in session.scalars(statement.limit(first + 1))]

        return connection(
            await db_call(read), first, lambda item: encode_cursor(scope, str(item.id))
        )

    @strawberry.field
    async def my_notifications(
        self, info: Info, first: int = 20, after: str | None = None
    ) -> Connection[Notification]:
        owner = info.context["workspace"].owner()
        page_size(first)
        scope = scope_key("notifications", str(owner))
        cursor = decode_cursor(after, scope)
        statement = (
            select(NotificationRow)
            .where(NotificationRow.owner_id == owner)
            .order_by(NotificationRow.id)
        )
        if cursor:
            statement = statement.where(NotificationRow.id > uuid_value(cursor[0]))

        def read() -> list[Notification]:
            with Session(engine()) as session:
                return [
                    Notification(
                        id=strawberry.ID(str(row.id)),
                        message=row.message,
                        created_at=row.created_at,
                        read_at=row.read_at,
                        target=row.package_id,
                    )
                    for row in session.scalars(statement.limit(first + 1))
                ]

        return connection(
            await db_call(read), first, lambda item: encode_cursor(scope, str(item.id))
        )
