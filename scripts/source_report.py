"""Read-only source totals for an administrative checks container."""

import json

from radar_common.database import database_url
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from services.catalog.domain_models import DependencyRow, PackageRow, ReleaseRow
from services.repositories.models import RepositoryRow
from services.security.models import AliasRow, VersionScanRow, VulnerabilityRow


def main() -> None:
    result: dict[str, object] = {}
    for owner in ("catalog", "repositories", "security"):
        database = create_engine(database_url(owner), hide_parameters=True)
        try:
            with Session(database) as session:
                if owner == "catalog":
                    result["pypi_packages"] = session.scalar(
                        select(func.count())
                        .select_from(PackageRow)
                        .where(PackageRow.source == "PYPI")
                    )
                    result["pypi_releases"] = session.scalar(
                        select(func.count())
                        .select_from(ReleaseRow)
                        .where(ReleaseRow.source == "PYPI")
                    )
                    result["pypi_requirements"] = session.scalar(
                        select(func.count())
                        .select_from(DependencyRow)
                        .join(ReleaseRow)
                        .where(ReleaseRow.source == "PYPI")
                    )
                    result["synthetic_packages"] = session.scalar(
                        select(func.count())
                        .select_from(PackageRow)
                        .where(PackageRow.source == "SYNTHETIC")
                    )
                elif owner == "repositories":
                    result["github_repositories"] = session.scalar(
                        select(func.count())
                        .select_from(RepositoryRow)
                        .where(RepositoryRow.source == "GITHUB")
                    )
                else:
                    result["osv_advisories"] = session.scalar(
                        select(func.count())
                        .select_from(VulnerabilityRow)
                        .where(VulnerabilityRow.source == "OSV")
                    )
                    result["osv_identifiers_including_aliases"] = session.scalar(
                        select(func.count())
                        .select_from(AliasRow)
                        .join(VulnerabilityRow)
                        .where(VulnerabilityRow.source == "OSV")
                    )
                    result["osv_scans"] = dict(
                        session.execute(
                            select(VersionScanRow.status, func.count())
                            .where(VersionScanRow.source == "OSV")
                            .group_by(VersionScanRow.status)
                        ).all()
                    )
        finally:
            database.dispose()
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
