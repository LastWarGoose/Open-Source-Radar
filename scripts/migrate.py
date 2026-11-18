"""Explicit single migration job; each service owns its migration history."""

import argparse
from pathlib import Path

from alembic import command
from alembic.config import Config
from radar_common.database import SERVICES, database_url
from sqlalchemy import create_engine


def migrate(service: str, revision: str = "head") -> None:
    config = Config()
    root = Path(__file__).resolve().parents[1]
    config.set_main_option("script_location", str(root / "services" / service / "migrations"))
    engine = create_engine(database_url(service), hide_parameters=True)
    try:
        with engine.begin() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, revision)
        print(f"Migration complete: {service}")
    finally:
        engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--service", choices=SERVICES)
    args = parser.parse_args()
    for service in (args.service,) if args.service else SERVICES:
        migrate(service)


if __name__ == "__main__":
    main()
