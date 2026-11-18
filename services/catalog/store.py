from datetime import datetime
from uuid import NAMESPACE_URL, UUID, uuid5

from packaging.version import Version
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from services.catalog.domain_models import DependencyRow, PackageRow, ReleaseRow
from services.catalog.normalization import (
    normalized_name,
    normalized_version,
    package_id,
    parse_requirement,
    release_id,
)


def save_package(
    session: Session,
    name: str,
    summary: str,
    fetched_at: datetime,
    *,
    source: str = "PYPI",
    license: str | None = None,
) -> str:
    identity = package_id(name)
    values = dict(
        id=identity,
        name=normalized_name(name),
        display_name=name,
        summary=summary,
        source=source,
        source_id=name,
        fetched_at=fetched_at,
        updated_at=fetched_at,
        license=license,
    )
    statement = insert(PackageRow).values(**values)
    session.execute(
        statement.on_conflict_do_update(
            index_elements=[PackageRow.id],
            set_={k: v for k, v in values.items() if k != "id"},
            where=PackageRow.fetched_at <= fetched_at,
        )
    )
    return identity


def save_release(
    session: Session,
    name: str,
    version: str,
    fetched_at: datetime,
    *,
    yanked: bool = False,
    source: str = "PYPI",
) -> UUID:
    identity = release_id(name, version)
    parent = package_id(name)
    # Serialize rank maintenance for one package; Version ordering, not lexicographic ordering.
    if (
        session.scalar(select(PackageRow.id).where(PackageRow.id == parent).with_for_update())
        is None
    ):
        raise ValueError("Unknown package")
    values = dict(
        id=identity,
        package_id=parent,
        version=version,
        normalized_version=normalized_version(version),
        version_rank=0,
        is_prerelease=Version(version).is_prerelease,
        yanked=yanked,
        source=source,
        fetched_at=fetched_at,
    )
    session.execute(
        insert(ReleaseRow)
        .values(**values)
        .on_conflict_do_update(
            index_elements=[ReleaseRow.package_id, ReleaseRow.normalized_version],
            set_={"yanked": yanked, "fetched_at": fetched_at, "source": source},
            where=ReleaseRow.fetched_at <= fetched_at,
        )
    )
    rows = list(session.scalars(select(ReleaseRow).where(ReleaseRow.package_id == parent)))
    for rank, row in enumerate(sorted(rows, key=lambda item: Version(item.version))):
        row.version_rank = rank
    return identity


def save_requirement(session: Session, release: UUID, raw: str) -> UUID:
    parsed = parse_requirement(raw)
    identity = uuid5(NAMESPACE_URL, str(release) + "/" + raw)
    session.execute(
        insert(DependencyRow)
        .values(
            id=identity,
            release_id=release,
            raw=parsed.raw,
            name=parsed.name,
            specifier=parsed.specifier,
            extras=parsed.extras,
            marker=parsed.marker,
            url=parsed.url,
        )
        .on_conflict_do_nothing(index_elements=[DependencyRow.release_id, DependencyRow.raw])
    )
    return identity
