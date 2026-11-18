from datetime import UTC, datetime, timedelta
from enum import Enum
from uuid import UUID

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
from radar_common.import_api import read_work
from sqlalchemy import Select, select
from sqlalchemy.orm import Session
from strawberry.dataloader import DataLoader
from strawberry.types import Info

from services.security.models import AliasRow, FindingRow, VersionScanRow, VulnerabilityRow


@strawberry.enum
class ScanStatus(Enum):
    UNKNOWN = "UNKNOWN"
    SUCCESS = "SUCCESS"
    STALE = "STALE"
    FAILED = "FAILED"


@strawberry.type
class AdvisoryAlias:
    name: str


@strawberry.federation.type(keys=["id"])
class Vulnerability:
    id: strawberry.ID
    summary: str
    source: str
    fetched_at: datetime

    @classmethod
    async def resolve_reference(cls, id: strawberry.ID, info: Info) -> "Vulnerability | None":
        row = await info.context["security"].vulnerabilities.load(str(id))
        return view(row) if row else None

    @strawberry.field
    async def aliases(
        self, info: Info, first: int = 20, after: str | None = None
    ) -> Connection[AdvisoryAlias]:
        rows = await info.context["security"].aliases.load(
            PageKey(str(self.id), page_size(first), after)
        )
        scope = scope_key("aliases", str(self.id))
        return connection(
            [AdvisoryAlias(name=row.alias) for row in rows],
            first,
            lambda item: encode_cursor(scope, item.name),
        )


def view(row: VulnerabilityRow) -> Vulnerability:
    return Vulnerability(
        id=strawberry.ID(row.id), summary=row.summary, source=row.source, fetched_at=row.fetched_at
    )


@strawberry.type
class VersionScan:
    id: strawberry.ID
    status: ScanStatus
    source: str
    checked_at: datetime | None
    last_success_at: datetime | None
    error_code: str | None

    @strawberry.field
    async def findings(
        self, info: Info, first: int = 20, after: str | None = None
    ) -> Connection[Vulnerability]:
        rows = await info.context["security"].findings.load(
            PageKey(str(self.id), page_size(first), after)
        )
        scope = scope_key("findings", str(self.id))
        return connection(
            [view(row) for row in rows], first, lambda item: encode_cursor(scope, str(item.id))
        )


@strawberry.federation.type(keys=["id"], extend=True)
class Release:
    id: strawberry.ID = strawberry.federation.field(external=True)

    @classmethod
    def resolve_reference(cls, id: strawberry.ID) -> "Release":
        return cls(id=id)

    @strawberry.field
    async def scan(self, info: Info) -> VersionScan | None:
        row = await info.context["security"].scans.load(str(self.id))
        return (
            VersionScan(
                id=strawberry.ID(str(row.id)),
                status=ScanStatus.STALE
                if row.status == "SUCCESS"
                and row.last_success_at
                and row.last_success_at < datetime.now(UTC) - timedelta(days=1)
                else ScanStatus(row.status),
                source=row.source,
                checked_at=row.checked_at,
                last_success_at=row.last_success_at,
                error_code=row.error_code,
            )
            if row
            else None
        )


class SecurityLoaders:
    def __init__(self) -> None:
        async def scans(keys: list[str]) -> list[VersionScanRow | None]:
            def read() -> list[VersionScanRow | None]:
                with Session(engine()) as session:
                    rows = {
                        row.release_id: row
                        for row in session.scalars(
                            select(VersionScanRow).where(VersionScanRow.release_id.in_(keys))
                        )
                    }
                    return [rows.get(key) for key in keys]

            return await db_call(read)

        async def vulnerabilities(keys: list[str]) -> list[VulnerabilityRow | None]:
            def read() -> list[VulnerabilityRow | None]:
                with Session(engine()) as session:
                    rows = {
                        row.id: row
                        for row in session.scalars(
                            select(VulnerabilityRow).where(VulnerabilityRow.id.in_(keys))
                        )
                    }
                    return [rows.get(key) for key in keys]

            return await db_call(read)

        def findings(key: PageKey) -> Select[VulnerabilityRow]:
            statement = (
                select(VulnerabilityRow)
                .join(FindingRow)
                .where(FindingRow.scan_id == UUID(key.parent))
            )
            values = decode_cursor(key.after, scope_key("findings", key.parent))
            if values:
                statement = statement.where(VulnerabilityRow.id > values[0])
            return statement

        def aliases(key: PageKey) -> Select[AliasRow]:
            statement = select(AliasRow).where(AliasRow.vulnerability_id == key.parent)
            values = decode_cursor(key.after, scope_key("aliases", key.parent))
            if values:
                statement = statement.where(AliasRow.alias > values[0])
            return statement

        self.scans = DataLoader(load_fn=scans, max_batch_size=100)
        self.vulnerabilities = DataLoader(load_fn=vulnerabilities, max_batch_size=100)
        self.findings = page_loader(VulnerabilityRow, findings, [VulnerabilityRow.id])
        self.aliases = page_loader(AliasRow, aliases, [AliasRow.alias])


async def context_getter() -> dict:
    return {"security": SecurityLoaders()}


@strawberry.type
class Query:
    security_import_job = strawberry.field(resolver=read_work)

    @strawberry.field
    async def vulnerability(self, info: Info, id: strawberry.ID) -> Vulnerability | None:
        return await Vulnerability.resolve_reference(id, info)
