import os
from functools import lru_cache

from sqlalchemy import URL, Engine, create_engine, text

SERVICES = ("catalog", "repositories", "security", "workspace")


def database_url(service: str | None = None) -> URL:
    name = service or os.environ["SERVICE_NAME"]
    if name not in SERVICES:
        raise ValueError("Unknown database owner")
    password = os.environ[f"{name.upper()}_DB_PASSWORD"] if service else os.environ["DB_PASSWORD"]
    return URL.create(
        "postgresql+psycopg",
        username=name,
        password=password,
        host=os.getenv("DB_HOST", "postgres"),
        port=5432,
        database=name,
    )


@lru_cache(maxsize=1)
def engine() -> Engine:
    # Created lazily, after Celery fork; never share live connections with child processes.
    return create_engine(
        database_url(),
        pool_pre_ping=True,
        pool_size=3,
        max_overflow=2,
        pool_timeout=5,
        hide_parameters=True,
        connect_args={"connect_timeout": 3, "options": "-c statement_timeout=5000"},
    )


def ready() -> bool:
    with engine().connect() as connection:
        connection.execute(text("SELECT version_num FROM alembic_version"))
    return True
