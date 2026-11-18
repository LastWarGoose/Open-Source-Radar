from collections import defaultdict
from dataclasses import dataclass
from uuid import UUID

from packaging.version import Version
from radar_common.database import engine
from radar_common.graphql import db_call
from radar_common.versions import nearest_version
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from services.security.models import FindingRow, VersionScanRow


async def nearest_scans(keys: list[tuple[str, Version]]) -> list[VersionScanRow | None]:
    def read() -> list[VersionScanRow | None]:
        by_package: dict[str, dict[Version, VersionScanRow]] = defaultdict(dict)
        with Session(engine()) as session:
            for row in session.scalars(
                select(VersionScanRow).where(
                    VersionScanRow.package_name.in_({name for name, _ in keys}),
                    VersionScanRow.source == "OSV",
                    VersionScanRow.last_success_at.is_not(None),
                )
            ):
                if row.package_name and row.version:
                    by_package[row.package_name][Version(row.version)] = row
        return [nearest_version(by_package[name], target) for name, target in keys]

    return await db_call(read)


@dataclass(frozen=True)
class FixKey:
    scan_id: UUID
    name: str
    version: Version


async def scan_fixes(keys: list[FixKey]) -> list[list[tuple[str, str, bool]]]:
    def read() -> list[list[tuple[str, str, bool]]]:
        current: dict[UUID, dict[str, str | None]] = defaultdict(dict)
        history: dict[str, dict[str, set[Version]]] = defaultdict(lambda: defaultdict(set))
        ids = {key.scan_id for key in keys}
        with Session(engine()) as session:
            rows = session.execute(
                select(
                    VersionScanRow.package_name,
                    FindingRow.scan_id,
                    FindingRow.vulnerability_id,
                    FindingRow.fixed_version,
                )
                .join(FindingRow, FindingRow.scan_id == VersionScanRow.id)
                .where(
                    VersionScanRow.source == "OSV",
                    VersionScanRow.package_name.in_({key.name for key in keys}),
                    or_(FindingRow.fixed_version.is_not(None), FindingRow.scan_id.in_(ids)),
                )
            )
            for name, scan_id, advisory, fixed in rows:
                if scan_id in ids:
                    current[scan_id][advisory] = fixed
                if name and fixed:
                    history[name][advisory].add(Version(fixed))
        results = []
        for key in keys:
            active = current[key.scan_id]
            fixes = [(advisory, fixed, False) for advisory, fixed in active.items() if fixed]
            for advisory, versions in history[key.name].items():
                if advisory not in active:
                    known = max((v for v in versions if v <= key.version), default=None)
                    if known is not None:
                        fixes.append((advisory, str(known), True))
            results.append(sorted(fixes, key=lambda f: (f[2], f[0])))
        return results

    return await db_call(read)
