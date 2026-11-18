"""Assign a role locally; never exposed as a public mutation."""

import argparse

from radar_common.database import engine
from sqlalchemy import select
from sqlalchemy.orm import Session

from services.workspace.accounts import username_value
from services.workspace.models import AccountRow


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("username")
    parser.add_argument("role", choices=["user", "admin"])
    args = parser.parse_args()
    with Session(engine()) as session, session.begin():
        row = session.scalar(
            select(AccountRow)
            .where(AccountRow.username == username_value(args.username))
            .with_for_update()
        )
        if row is None:
            raise SystemExit("Account not found; register it on the website first")
        row.role = args.role
    print("Account role updated")


if __name__ == "__main__":
    main()
