from datetime import datetime
from enum import Enum

import strawberry
from radar_common.database import engine
from radar_common.graphql import (
    Connection,
    PageKey,
    connection,
    db_call,
    decode_cursor,
    encode_cursor,
    page_loader,
    page_size,
    scope_key,
)
from radar_common.source_graphql import SourceFreshness, freshness_loader, freshness_view
from sqlalchemy import Select, select
from sqlalchemy.orm import Session
from strawberry.dataloader import DataLoader
from strawberry.types import Info

from services.repositories.models import PackageRepositoryRow, RepositoryRow


@strawberry.enum
class RepositoryLinkStatus(Enum):
    UNVERIFIED = "UNVERIFIED"
    VERIFIED = "VERIFIED"
    INVALID = "INVALID"


@strawberry.federation.type(keys=["id"])
class Repository:
    id: strawberry.ID
    full_name: str
    description: str | None
    url: str
    stars: int
    source: str
    source_id: str
    fetched_at: datetime

    @classmethod
    async def resolve_reference(cls, id: strawberry.ID, info: Info) -> "Repository | None":
        row = await info.context["repositories"].by_id.load(str(id))
        return view(row) if row else None


def view(row: RepositoryRow) -> Repository:
    return Repository(
        id=strawberry.ID(row.id),
        full_name=row.full_name,
        description=row.description,
        url=row.url,
        stars=row.stars,
        source=row.source,
        source_id=row.source_id,
        fetched_at=row.fetched_at,
    )


@strawberry.type
class RepositoryLink:
    status: RepositoryLinkStatus
    target: strawberry.Private[str]

    @strawberry.field
    async def repository(self, info: Info) -> Repository | None:
        return await Repository.resolve_reference(strawberry.ID(self.target), info)


@strawberry.federation.type(keys=["id"], extend=True)
class Package:
    id: strawberry.ID = strawberry.federation.field(external=True)

    @strawberry.field
    async def github_freshness(self, info: Info) -> SourceFreshness | None:
        return freshness_view(await info.context["freshness"].load(str(self.id)))

    @classmethod
    def resolve_reference(cls, id: strawberry.ID) -> "Package":
        return cls(id=id)

    @strawberry.field
    async def repositories(
        self, info: Info, first: int = 20, after: str | None = None
    ) -> Connection[RepositoryLink] | None:
        rows = await info.context["repositories"].links.load(
            PageKey(str(self.id), page_size(first), after)
        )
        scope = scope_key("repositories", str(self.id))
        return connection(
            [
                RepositoryLink(status=RepositoryLinkStatus(row.status), target=row.repository_id)
                for row in rows
            ],
            first,
            lambda item: encode_cursor(scope, item.target),
        )


class RepositoryLoaders:
    def __init__(self) -> None:
        async def load(keys: list[str]) -> list[RepositoryRow | None]:
            def read() -> list[RepositoryRow | None]:
                with Session(engine()) as session:
                    rows = {
                        row.id: row
                        for row in session.scalars(
                            select(RepositoryRow).where(RepositoryRow.id.in_(keys))
                        )
                    }
                    return [rows.get(key) for key in keys]

            return await db_call(read)

        def query(key: PageKey) -> Select[PackageRepositoryRow]:
            statement = select(PackageRepositoryRow).where(
                PackageRepositoryRow.package_id == key.parent
            )
            values = decode_cursor(key.after, scope_key("repositories", key.parent))
            if values:
                statement = statement.where(PackageRepositoryRow.repository_id > values[0])
            return statement

        self.by_id = DataLoader(load_fn=load, max_batch_size=100)
        self.links = page_loader(PackageRepositoryRow, query, [PackageRepositoryRow.repository_id])


async def context_getter() -> dict:
    return {"repositories": RepositoryLoaders(), "freshness": freshness_loader()}


@strawberry.type
class DomainQuery:
    @strawberry.field
    async def repository(self, info: Info, id: strawberry.ID) -> Repository | None:
        return await Repository.resolve_reference(id, info)
