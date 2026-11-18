import re
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from enum import Enum
from uuid import UUID

import strawberry
from graphql import GraphQLError
from packaging.version import InvalidVersion, Version
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
from radar_common.session import require_admin
from radar_common.source_graphql import SourceFreshness, freshness_loader, freshness_view
from radar_common.versions import nearest_version
from sqlalchemy import (
    ARRAY,
    Integer,
    Select,
    String,
    and_,
    case,
    cast,
    func,
    literal_column,
    or_,
    select,
    true,
    tuple_,
)
from sqlalchemy.orm import Session, aliased
from strawberry.dataloader import DataLoader
from strawberry.types import Info

from services.catalog.domain_models import DependencyRow, ImportJobRow, PackageRow, ReleaseRow


def uuid_value(value: str) -> UUID:
    try:
        return UUID(value)
    except ValueError:
        raise invalid("Invalid UUID") from None


@strawberry.enum
class PackageSort(Enum):
    RELEVANCE = "RELEVANCE"
    NAME_ASC = "NAME_ASC"
    UPDATED_DESC = "UPDATED_DESC"
    STARS_DESC = "STARS_DESC"


@strawberry.input
class PackageFilter:
    license: str | None = None
    has_releases: bool | None = None
    source: str | None = None


def source_filter(source: str | None) -> str | None:
    if source not in (None, "PYPI", "SYNTHETIC"):
        raise invalid("Invalid data source")
    return source


@strawberry.type
class StarProjection:
    stars: int | None
    checked_at: datetime | None
    projected_at: datetime | None
    status: str
    lag_seconds: int | None


@strawberry.federation.type(keys=["id"])
class Package:
    id: strawberry.ID
    name: str
    display_name: str
    summary: str
    license: str | None
    requires_python: str | None
    source: str
    source_id: str
    fetched_at: datetime
    updated_at: datetime
    star_projection: StarProjection

    @strawberry.field
    async def pypi_freshness(self, info: Info) -> SourceFreshness:
        return freshness_view(await info.context["freshness"].load(str(self.id)))

    @classmethod
    async def resolve_reference(cls, id: strawberry.ID, info: Info) -> "Package | None":
        row = await info.context["catalog"].packages.load(str(id))
        if row is None:
            raise GraphQLError("Referenced package not found", extensions={"code": "NOT_FOUND"})
        return package_view(row)

    @strawberry.field
    async def releases(
        self, info: Info, first: int = 20, after: str | None = None, source: str | None = None
    ) -> Connection["Release"]:
        source_filter(source)
        key = str(self.id) + ("/" + source if source else "")
        rows = await info.context["catalog"].releases.load(PageKey(key, page_size(first), after))
        scope = scope_key("releases", key)
        return connection(
            [release_view(row) for row in rows],
            first,
            lambda item: encode_cursor(scope, str(item.rank), str(item.id)),
        )

    @strawberry.field
    async def nearest_pypi_release(self, info: Info, version: str) -> "Release | None":
        if len(version) > 200:
            raise invalid("Invalid version")
        try:
            key = (str(self.id), Version(version))
        except InvalidVersion:
            raise invalid("Invalid version") from None
        loaders = info.context["catalog"]
        identity = await loaders.nearest_pypi.load(key)
        row = await loaders.release_by_id.load(str(identity)) if identity else None
        return release_view(row) if row else None

    @strawberry.field
    async def release(self, info: Info, version: str, source: str = "PYPI") -> "Release | None":
        from services.catalog.normalization import release_id

        source_filter(source)
        try:
            identity = release_id(self.name, version)
        except ValueError:
            raise invalid("Invalid version") from None
        row = await info.context["catalog"].release_by_id.load(str(identity))
        return (
            release_view(row)
            if row and row.package_id == str(self.id) and row.source == source
            else None
        )


@strawberry.federation.type(keys=["id"])
class Release:
    id: strawberry.ID
    version: str
    normalized_version: str
    is_prerelease: bool
    yanked: bool
    source: str
    fetched_at: datetime
    parent: strawberry.Private[str]
    rank: strawberry.Private[int]

    @classmethod
    async def resolve_reference(cls, id: strawberry.ID, info: Info) -> "Release | None":
        row = await info.context["catalog"].release_by_id.load(str(uuid_value(str(id))))
        return release_view(row) if row else None

    @strawberry.field
    async def package(self, info: Info) -> Package | None:
        row = await info.context["catalog"].packages.load(self.parent)
        return package_view(row) if row else None

    @strawberry.field
    async def dependencies(
        self, info: Info, first: int = 20, after: str | None = None
    ) -> Connection["DependencyRequirement"]:
        rows = await info.context["catalog"].dependencies.load(
            PageKey(str(self.id), page_size(first), after)
        )
        scope = scope_key("dependencies", str(self.id))
        return connection(
            [dependency_view(row) for row in rows],
            first,
            lambda item: encode_cursor(scope, str(item.id)),
        )


@strawberry.type
class DependencyRequirement:
    id: strawberry.ID
    raw: str
    name: str
    specifier: str
    extras: list[str]
    marker: str | None
    url: str | None

    @strawberry.field
    async def package(self, info: Info) -> Package | None:
        row = await info.context["catalog"].packages.load("pypi:" + self.name)
        return package_view(row) if row else None


@strawberry.type
class ImportJob:
    id: strawberry.ID
    status: str
    source: str
    processed: int
    error_code: str | None
    created_at: datetime
    completed_at: datetime | None
    can_resume: bool = True


def package_view(row: PackageRow) -> Package:
    return Package(
        id=strawberry.ID(row.id),
        name=row.name,
        display_name=row.display_name,
        summary=row.summary,
        license=row.license,
        requires_python=row.requires_python,
        source=row.source,
        source_id=row.source_id,
        fetched_at=row.fetched_at,
        updated_at=row.updated_at,
        star_projection=StarProjection(
            stars=row.github_stars,
            checked_at=row.github_checked_at,
            projected_at=row.github_projected_at,
            status="STALE"
            if row.github_status == "SUCCESS"
            and row.github_checked_at
            and row.github_checked_at < datetime.now(UTC) - timedelta(days=1)
            else row.github_status,
            lag_seconds=max(
                0, int((row.github_projected_at - row.github_checked_at).total_seconds())
            )
            if row.github_checked_at and row.github_projected_at
            else None,
        ),
    )


def release_view(row: ReleaseRow) -> Release:
    return Release(
        id=strawberry.ID(str(row.id)),
        version=row.version,
        normalized_version=row.normalized_version,
        is_prerelease=row.is_prerelease,
        yanked=row.yanked,
        source=row.source,
        fetched_at=row.fetched_at,
        parent=row.package_id,
        rank=row.version_rank,
    )


def dependency_view(row: DependencyRow) -> DependencyRequirement:
    return DependencyRequirement(
        id=strawberry.ID(str(row.id)),
        raw=row.raw,
        name=row.name,
        specifier=row.specifier,
        extras=row.extras,
        marker=row.marker,
        url=row.url,
    )


def release_query(key: PageKey) -> Select[ReleaseRow]:
    parent, _, source = key.parent.partition("/")
    statement = select(ReleaseRow).where(ReleaseRow.package_id == parent)
    if source:
        statement = statement.where(ReleaseRow.source == source_filter(source))
    values = decode_cursor(key.after, scope_key("releases", key.parent), 2)
    if values:
        try:
            rank = int(values[0])
        except ValueError:
            raise invalid("Invalid version cursor") from None
        statement = statement.where(
            or_(
                ReleaseRow.version_rank < rank,
                and_(ReleaseRow.version_rank == rank, ReleaseRow.id > uuid_value(values[1])),
            )
        )
    return statement


def release_first_pages(keys: list[PageKey]) -> list[list[ReleaseRow]] | None:
    # Catalog rows usually request the same release page for every parent. PostgreSQL
    # can reuse one parameterized plan and stop at the per-parent index limit.
    first = keys[0].first
    source = keys[0].parent.partition("/")[2]
    if any(k.after or k.first != first or k.parent.partition("/")[2] != source for k in keys):
        return None
    ids = [k.parent.partition("/")[0] for k in keys]
    parents = func.unnest(cast(ids, ARRAY(String))).table_valued("id").render_derived()
    rows = select(ReleaseRow).where(ReleaseRow.package_id == parents.c.id)
    if source:
        rows = rows.where(ReleaseRow.source == source_filter(source))
    limited = (
        rows.order_by(ReleaseRow.version_rank.desc(), ReleaseRow.id)
        .limit(first + 1)
        .correlate(parents)
        .lateral()
    )
    release = aliased(ReleaseRow, limited)
    statement = (
        select(release)
        .select_from(parents.join(limited, true()))
        .order_by(release.package_id, release.version_rank.desc(), release.id)
    )
    groups: dict[str, list[ReleaseRow]] = {identity: [] for identity in ids}
    with Session(engine()) as session:
        for row in session.scalars(statement):
            groups[row.package_id].append(row)
    return [groups[identity] for identity in ids]


def dependency_query(key: PageKey) -> Select[DependencyRow]:
    statement = select(DependencyRow).where(DependencyRow.release_id == uuid_value(key.parent))
    values = decode_cursor(key.after, scope_key("dependencies", key.parent))
    if values:
        statement = statement.where(DependencyRow.id > uuid_value(values[0]))
    return statement


class CatalogLoaders:
    def __init__(self) -> None:
        async def packages(keys: list[str]) -> list[PackageRow | None]:
            def read() -> list[PackageRow | None]:
                with Session(engine()) as session:
                    rows = {
                        row.id: row
                        for row in session.scalars(
                            select(PackageRow).where(PackageRow.id.in_(keys))
                        )
                    }
                    return [rows.get(key) for key in keys]

            return await db_call(read)

        async def releases(keys: list[str]) -> list[ReleaseRow | None]:
            def read() -> list[ReleaseRow | None]:
                with Session(engine()) as session:
                    rows = {
                        str(row.id): row
                        for row in session.scalars(
                            select(ReleaseRow).where(ReleaseRow.id.in_([UUID(key) for key in keys]))
                        )
                    }
                    return [rows.get(key) for key in keys]

            return await db_call(read)

        async def nearest(keys: list[tuple[str, Version]]) -> list[UUID | None]:
            def read() -> list[UUID | None]:
                grouped: dict[str, dict[Version, UUID]] = defaultdict(dict)
                with Session(engine()) as session:
                    for name, version, identity in session.execute(
                        select(ReleaseRow.package_id, ReleaseRow.version, ReleaseRow.id).where(
                            ReleaseRow.package_id.in_({pkg for pkg, _ in keys}),
                            ReleaseRow.source == "PYPI",
                        )
                    ):
                        grouped[name][Version(version)] = identity
                return [nearest_version(grouped[pkg], target) for pkg, target in keys]

            return await db_call(read)

        self.nearest_pypi = DataLoader(load_fn=nearest, max_batch_size=100)
        self.packages = DataLoader(load_fn=packages, max_batch_size=100)
        self.release_by_id = DataLoader(load_fn=releases, max_batch_size=100)
        self.releases = page_loader(
            ReleaseRow,
            release_query,
            [ReleaseRow.version_rank.desc(), ReleaseRow.id],
            release_first_pages,
        )
        self.dependencies = page_loader(DependencyRow, dependency_query, [DependencyRow.id])


async def context_getter() -> dict:
    return {"catalog": CatalogLoaders(), "freshness": freshness_loader()}


@strawberry.type
class DomainQuery:
    @strawberry.field
    async def package(self, info: Info, id: strawberry.ID) -> Package | None:
        row = await info.context["catalog"].packages.load(str(id))
        return package_view(row) if row else None

    @strawberry.field
    async def release(self, info: Info, id: strawberry.ID) -> Release | None:
        return await Release.resolve_reference(id, info)

    @strawberry.field
    async def catalog_licenses(self, first: int = 100, after: str | None = None) -> Connection[str]:
        size = page_size(first)
        scope = scope_key("catalogLicenses", "PYPI")
        cursor = decode_cursor(after, scope)
        column = PackageRow.license_key
        statement = select(column).where(PackageRow.source == "PYPI", column.is_not(None))
        if cursor:
            statement = statement.where(column > cursor[0])

        def read() -> list[str]:
            with Session(engine()) as session:
                return [
                    v
                    for v in session.scalars(statement.distinct().order_by(column).limit(size + 1))
                    if v is not None
                ]

        return connection(await db_call(read), size, lambda key: encode_cursor(scope, key))

    @strawberry.field
    async def packages(
        self,
        first: int = 20,
        after: str | None = None,
        search: str | None = None,
        filter: PackageFilter | None = None,
        sort: PackageSort = PackageSort.NAME_ASC,
    ) -> Connection[Package]:
        page_size(first)
        term = (search or "").strip()
        license = filter.license if filter else None
        has_releases = filter.has_releases if filter else None
        source = source_filter(filter.source if filter else None)
        if len(term) > 200 or (license is not None and len(license) > 200):
            raise invalid("Search or filter too long")
        if sort == PackageSort.RELEVANCE and not term:
            sort = PackageSort.STARS_DESC
        # Old relevance cursors represent alphabetical ties and cannot resume the new ranking.
        order_key = "RELEVANCE_V2" if sort == PackageSort.RELEVANCE else sort.value
        scope = scope_key("packages", term, license, has_releases, order_key, source)
        cursor = decode_cursor(after, scope, 2)
        statement = select(PackageRow)
        if source is not None:
            statement = statement.where(PackageRow.source == source)
        if license is not None:
            statement = statement.where(
                or_(PackageRow.license_key == license, PackageRow.license == license)
            )
        if has_releases is not None:
            exists = select(ReleaseRow.id).where(ReleaseRow.package_id == PackageRow.id).exists()
            if source:
                exists = (
                    select(ReleaseRow.id)
                    .where(ReleaseRow.package_id == PackageRow.id, ReleaseRow.source == source)
                    .exists()
                )
            statement = statement.where(exists if has_releases else ~exists)
        if term:
            # Escape SQL LIKE wildcards; user text never becomes SQL or GraphQL source.
            name_term = re.sub(r"[-_.]+", "-", term.lower())
            escaped = name_term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            vector = func.to_tsvector(
                literal_column("'simple'"), PackageRow.name + " " + PackageRow.summary
            )
            query = func.websearch_to_tsquery(literal_column("'simple'"), term)
            in_name = PackageRow.name.ilike("%" + escaped + "%", escape="\\")
            statement = statement.where(or_(in_name, vector.op("@@")(query)))
        if sort == PackageSort.RELEVANCE and term:
            tier = case(
                (PackageRow.name == name_term, 3),
                (PackageRow.name.like(escaped + "%", escape="\\"), 2),
                (PackageRow.name.like("%" + escaped + "%", escape="\\"), 1),
                else_=0,
            )
            # Quantize the bounded scores so the key round-trips exactly in a cursor.
            text_score = func.ts_rank_cd(vector, query, 32)
            name_score = case((in_name, func.similarity(PackageRow.name, name_term)), else_=0)
            rank = tier * 1_000_000 + cast(
                func.floor(100_000 * text_score + 10_000 * name_score), Integer
            )
            ranked = statement.add_columns(rank).order_by(rank.desc(), PackageRow.id)
            if cursor:
                if not re.fullmatch(r"[0-9]{1,7}", cursor[0]):
                    raise invalid("Invalid relevance cursor")
                value = int(cursor[0])
                ranked = ranked.where(
                    or_(rank < value, and_(rank == value, PackageRow.id > cursor[1]))
                )

            def read_ranked() -> list[tuple[Package, int]]:
                with Session(engine()) as session:
                    return [
                        (package_view(row), value)
                        for row, value in session.execute(ranked.limit(first + 1))
                    ]

            ranked_rows = await db_call(read_ranked)
            positions = {item.id: str(value) for item, value in ranked_rows}
            return connection(
                [item for item, _ in ranked_rows],
                first,
                lambda item: encode_cursor(scope, positions[item.id], str(item.id)),
            )
        if sort == PackageSort.NAME_ASC:
            statement = statement.order_by(PackageRow.name, PackageRow.id)
            if cursor:
                statement = statement.where(
                    tuple_(PackageRow.name, PackageRow.id) > tuple_(*cursor)
                )
        elif sort == PackageSort.STARS_DESC:
            score = func.coalesce(PackageRow.github_stars, -1)
            statement = statement.order_by(score.desc(), PackageRow.id)
            if cursor:
                try:
                    stars = int(cursor[0])
                    if stars < -1:
                        raise ValueError
                except ValueError:
                    raise invalid("Invalid stars cursor") from None
                statement = statement.where(
                    or_(score < stars, and_(score == stars, PackageRow.id > cursor[1]))
                )
        else:
            statement = statement.order_by(PackageRow.updated_at.desc(), PackageRow.id)
            if cursor:
                try:
                    timestamp = datetime.fromisoformat(cursor[0])
                    if timestamp.tzinfo is None:
                        raise ValueError
                except ValueError:
                    raise invalid("Invalid timestamp cursor") from None
                statement = statement.where(
                    or_(
                        PackageRow.updated_at < timestamp,
                        and_(PackageRow.updated_at == timestamp, PackageRow.id > cursor[1]),
                    )
                )

        def read() -> list[PackageRow]:
            with Session(engine()) as session:
                return list(session.scalars(statement.limit(first + 1)))

        rows = [package_view(row) for row in await db_call(read)]
        return connection(
            rows,
            first,
            lambda item: encode_cursor(
                scope,
                item.name
                if sort == PackageSort.NAME_ASC
                else str(
                    item.star_projection.stars if item.star_projection.stars is not None else -1
                )
                if sort == PackageSort.STARS_DESC
                else item.updated_at.isoformat(),
                str(item.id),
            ),
        )

    @strawberry.field
    async def import_jobs(
        self, info: Info, first: int = 20, after: str | None = None
    ) -> Connection[ImportJob]:
        await require_admin(info)
        page_size(first)
        scope = scope_key("importJobs")
        cursor = decode_cursor(after, scope)
        statement = select(ImportJobRow).order_by(ImportJobRow.id)
        if cursor:
            statement = statement.where(ImportJobRow.id > uuid_value(cursor[0]))

        def read() -> list[ImportJob]:
            with Session(engine()) as session:
                return [
                    ImportJob(
                        id=strawberry.ID(str(row.id)),
                        status=row.status,
                        source=row.source,
                        processed=row.processed,
                        error_code=row.error_code,
                        created_at=row.created_at,
                        completed_at=row.completed_at,
                        can_resume="campaign" not in row.checkpoint,
                    )
                    for row in session.scalars(statement.limit(first + 1))
                ]

        return connection(
            await db_call(read), first, lambda item: encode_cursor(scope, str(item.id))
        )
