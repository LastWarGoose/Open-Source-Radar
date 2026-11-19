from datetime import UTC, datetime
from uuid import UUID, uuid5

import httpx
import strawberry
from radar_common.database import engine
from radar_common.graphql import (
    Connection,
    connection,
    db_call,
    decode_cursor,
    encode_cursor,
    page_size,
    scope_key,
)
from radar_common.session import internal
from radar_common.tracing import trace_headers
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session
from strawberry.types import Info

from services.workspace.accounts import fail
from services.workspace.auth_graphql import mutation_origin
from services.workspace.domain_graphql import Collection, Package, collection_view, uuid_value
from services.workspace.models import CollectionItemRow, CollectionRow, FollowRow, NotificationRow


async def package_snapshot(identity: str) -> dict:
    if len(identity) > 220:
        raise fail("Неверный пакет")
    async with httpx.AsyncClient(timeout=5) as client:
        try:
            response = await client.post(
                "http://catalog:8000/graphql",
                headers=trace_headers(),
                json={
                    "query": """query FollowTarget($id: ID!) { package(id: $id) {
                        id fetchedAt releases(first: 1, source: "PYPI") { nodes { version } }
                    } }""",
                    "variables": {"id": identity},
                },
            )
            result = response.json()
            if response.status_code != 200 or result.get("errors"):
                raise ValueError
            package = result["data"]["package"]
        except (httpx.HTTPError, ValueError, KeyError):
            raise fail("Каталог недоступен", "UNAVAILABLE") from None
    if package is None:
        raise fail("Пакет не найден")
    return package


def owner(info: Info) -> UUID:
    mutation_origin(info)
    return info.context["workspace"].owner()


def owned(session: Session, identity: UUID, actor: UUID) -> CollectionRow:
    row = session.scalar(
        select(CollectionRow)
        .where(CollectionRow.id == identity, CollectionRow.owner_id == actor)
        .with_for_update()
    )
    if row is None:
        raise fail("Подборка не найдена", "NOT_FOUND")
    return row


@strawberry.type
class Follow:
    package_id: strawberry.Private[str]
    version: str | None

    @strawberry.field
    def package(self) -> Package | None:
        return Package(id=strawberry.ID(self.package_id))


@strawberry.type
class PersonalQuery:
    @strawberry.field
    async def my_followed_package_ids(
        self, info: Info, package_ids: list[strawberry.ID]
    ) -> list[str]:
        actor = info.context["workspace"].owner()
        page_size(len(package_ids))
        if any(len(identity) > 220 for identity in package_ids):
            raise fail("Неверный пакет")

        def read() -> list[str]:
            with Session(engine()) as session:
                return list(
                    session.scalars(
                        select(FollowRow.package_id)
                        .where(FollowRow.owner_id == actor, FollowRow.package_id.in_(package_ids))
                        .order_by(FollowRow.package_id)
                    )
                )

        return await db_call(read)

    @strawberry.field
    async def followed_package_batch(
        self, info: Info, after_id: str = "", first: int = 2
    ) -> list[str]:
        if not internal(info.context["request"]):
            raise fail("Internal credential required", "FORBIDDEN")
        page_size(first)

        def read() -> list[str]:
            with Session(engine()) as session:
                return list(
                    session.scalars(
                        select(FollowRow.package_id)
                        .distinct()
                        .where(FollowRow.package_id > after_id)
                        .order_by(FollowRow.package_id)
                        .limit(first)
                    )
                )

        return await db_call(read)

    @strawberry.field
    async def my_follows(
        self, info: Info, first: int = 20, after: str | None = None
    ) -> Connection[Follow]:
        actor = info.context["workspace"].owner()
        page_size(first)
        scope = scope_key("follows", str(actor))
        cursor = decode_cursor(after, scope)

        def read() -> list[Follow]:
            statement = select(FollowRow).where(FollowRow.owner_id == actor)
            if cursor:
                statement = statement.where(FollowRow.package_id > cursor[0])
            with Session(engine()) as session:
                return [
                    Follow(package_id=row.package_id, version=row.version)
                    for row in session.scalars(
                        statement.order_by(FollowRow.package_id).limit(first + 1)
                    )
                ]

        return connection(
            await db_call(read), first, lambda row: encode_cursor(scope, row.package_id)
        )


@strawberry.type
class PersonalMutation:
    @strawberry.mutation
    async def create_collection(self, info: Info, name: str) -> Collection:
        actor = owner(info)
        name = name.strip()
        if not 1 <= len(name) <= 200:
            raise fail("Название: от 1 до 200 символов")

        def create() -> Collection:
            with Session(engine()) as session, session.begin():
                session.execute(
                    insert(CollectionRow).values(owner_id=actor, name=name).on_conflict_do_nothing()
                )
                row = session.scalar(
                    select(CollectionRow).where(
                        CollectionRow.owner_id == actor, CollectionRow.name == name
                    )
                )
                assert row
                return collection_view(row)

        return await db_call(create)

    @strawberry.mutation
    async def delete_collection(self, info: Info, id: strawberry.ID) -> bool:
        actor = owner(info)
        identity = uuid_value(str(id))

        def remove() -> None:
            with Session(engine()) as session, session.begin():
                session.delete(owned(session, identity, actor))

        await db_call(remove)
        info.context["workspace"].items.clear_all()
        return True

    @strawberry.mutation
    async def add_package_to_collection(
        self, info: Info, id: strawberry.ID, package_id: strawberry.ID
    ) -> Collection:
        actor = owner(info)
        identity = uuid_value(str(id))
        await package_snapshot(str(package_id))

        def add() -> Collection:
            with Session(engine()) as session, session.begin():
                row = owned(session, identity, actor)
                session.execute(
                    insert(CollectionItemRow)
                    .values(collection_id=identity, package_id=str(package_id))
                    .on_conflict_do_nothing()
                )
                return collection_view(row)

        value = await db_call(add)
        info.context["workspace"].items.clear_all()
        return value

    @strawberry.mutation
    async def remove_package_from_collection(
        self, info: Info, id: strawberry.ID, package_id: strawberry.ID
    ) -> Collection:
        actor = owner(info)
        identity = uuid_value(str(id))

        def remove() -> Collection:
            with Session(engine()) as session, session.begin():
                row = owned(session, identity, actor)
                session.execute(
                    delete(CollectionItemRow).where(
                        CollectionItemRow.collection_id == identity,
                        CollectionItemRow.package_id == str(package_id),
                    )
                )
                return collection_view(row)

        value = await db_call(remove)
        info.context["workspace"].items.clear_all()
        return value

    @strawberry.mutation
    async def follow_package(self, info: Info, package_id: strawberry.ID) -> bool:
        actor = owner(info)
        snapshot = await package_snapshot(str(package_id))
        versions = snapshot["releases"]["nodes"]

        def follow() -> None:
            with Session(engine()) as session, session.begin():
                session.execute(
                    insert(FollowRow)
                    .values(
                        owner_id=actor,
                        package_id=str(package_id),
                        version=versions[0]["version"] if versions else None,
                        observed_at=datetime.fromisoformat(snapshot["fetchedAt"]),
                    )
                    .on_conflict_do_nothing()
                )

        await db_call(follow)
        return True

    @strawberry.mutation
    async def unfollow_package(self, info: Info, package_id: strawberry.ID) -> bool:
        actor = owner(info)

        def remove() -> None:
            with Session(engine()) as session, session.begin():
                session.execute(
                    delete(FollowRow).where(
                        FollowRow.owner_id == actor, FollowRow.package_id == str(package_id)
                    )
                )

        await db_call(remove)
        return True

    @strawberry.mutation
    async def mark_notification_read(self, info: Info, id: strawberry.ID) -> bool:
        actor = owner(info)
        identity = uuid_value(str(id))

        def mark() -> None:
            with Session(engine()) as session, session.begin():
                row = session.scalar(
                    select(NotificationRow).where(
                        NotificationRow.id == identity, NotificationRow.owner_id == actor
                    )
                )
                if row is None:
                    raise fail("Уведомление не найдено", "NOT_FOUND")
                row.read_at = row.read_at or datetime.now(UTC)

        await db_call(mark)
        return True

    @strawberry.mutation
    async def record_package_update(
        self, info: Info, package_id: strawberry.ID, version: str, observed_at: datetime
    ) -> bool:
        if not internal(info.context["request"]):
            raise fail("Internal credential required", "FORBIDDEN")
        if len(str(package_id)) > 220 or len(version) > 200 or observed_at.tzinfo is None:
            raise fail("Invalid event")
        await db_call(record_update, str(package_id), version, observed_at)
        return True


def record_update(package: str, version: str, observed: datetime) -> None:
    with Session(engine()) as session, session.begin():
        for row in session.scalars(
            select(FollowRow).where(FollowRow.package_id == package).with_for_update()
        ):
            if observed <= row.observed_at:
                continue
            if version != row.version:
                session.execute(
                    insert(NotificationRow)
                    .values(
                        id=uuid5(row.owner_id, package + ":" + version),
                        owner_id=row.owner_id,
                        package_id=package,
                        message=f"{package.removeprefix('pypi:')}: версия {version}",
                    )
                    .on_conflict_do_nothing()
                )
            row.version = version
            row.observed_at = observed
