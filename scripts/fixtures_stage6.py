"""Create/remove only this run's explicitly marked browser fixtures."""

import os
import sys
from datetime import UTC, datetime
from uuid import UUID

from radar_common.database import engine
from radar_common.import_queue import Work
from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from scripts.check_stage3 import owner
from scripts.check_stage6 import cleanup
from services.catalog.domain_models import ImportJobRow, PackageRow
from services.catalog.normalization import package_id
from services.catalog.store import save_package, save_release
from services.workspace.accounts import register
from services.workspace.models import AccountRow

MARKER = "Synthetic stage 6 browser fixture"


def main() -> None:
    prefix = os.environ["STAGE6_RUN"]
    assert prefix.startswith("radar6ui-") and len(prefix) == 21
    names = [prefix + suffix for suffix in ("a", "b", "admin")]
    package = prefix + "-package"
    if sys.argv[1] == "seed":
        owner("workspace")
        for name in names[1:]:
            register(name, os.environ["STAGE6_PASSWORD"])
        with Session(engine()) as session, session.begin():
            session.execute(
                update(AccountRow).where(AccountRow.username == names[2]).values(role="admin")
            )
        owner("catalog")
        with Session(engine()) as session, session.begin():
            assert session.get(PackageRow, package_id(package)) is None
            save_package(session, package, MARKER, datetime.now(UTC))
            save_release(session, package, "1.0", datetime.now(UTC))
    else:
        cleanup(names)
        owner("catalog")
        with Session(engine()) as session, session.begin():
            parents = list(
                session.scalars(
                    select(ImportJobRow.id).where(
                        ImportJobRow.request_key == UUID(os.environ["STAGE6_JOB_KEY"])
                    )
                )
            )
            session.execute(delete(Work).where(Work.parent_id.in_(parents)))
            session.execute(delete(ImportJobRow).where(ImportJobRow.id.in_(parents)))
            session.execute(
                delete(PackageRow).where(
                    PackageRow.id == package_id(package), PackageRow.summary == MARKER
                )
            )
    print("PASS: stage 6 browser fixture " + sys.argv[1])


if __name__ == "__main__":
    main()
