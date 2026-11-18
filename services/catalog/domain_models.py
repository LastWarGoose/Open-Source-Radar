from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from services.catalog.models import Base


class PackageRow(Base):
    __tablename__ = "packages"
    id: Mapped[str] = mapped_column(String(220), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), unique=True)
    display_name: Mapped[str] = mapped_column(String(200))
    summary: Mapped[str] = mapped_column(Text)
    license: Mapped[str | None] = mapped_column(String(200))
    requires_python: Mapped[str | None] = mapped_column(String(200))
    source: Mapped[str] = mapped_column(String(32))
    source_id: Mapped[str] = mapped_column(String(200))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    github_stars: Mapped[int | None] = mapped_column(Integer)
    github_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    github_projected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    github_status: Mapped[str] = mapped_column(
        String(16), default="UNKNOWN", server_default="UNKNOWN"
    )
    __table_args__ = (
        CheckConstraint(
            "name = lower(name) AND name ~ '^[a-z0-9]+(-[a-z0-9]+)*$'",
            name="normalized_package_name",
        ),
    )


class ReleaseRow(Base):
    __tablename__ = "releases"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    package_id: Mapped[str] = mapped_column(
        ForeignKey("packages.id", ondelete="CASCADE"), index=True
    )
    version: Mapped[str] = mapped_column(String(200))
    normalized_version: Mapped[str] = mapped_column(String(200))
    version_rank: Mapped[int] = mapped_column(Integer)
    is_prerelease: Mapped[bool] = mapped_column(Boolean)
    yanked: Mapped[bool] = mapped_column(Boolean, default=False)
    source: Mapped[str] = mapped_column(String(32))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    __table_args__ = (UniqueConstraint("package_id", "normalized_version"),)


class DependencyRow(Base):
    __tablename__ = "dependency_requirements"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    release_id: Mapped[UUID] = mapped_column(
        ForeignKey("releases.id", ondelete="CASCADE"), index=True
    )
    raw: Mapped[str] = mapped_column(String(4096))
    name: Mapped[str] = mapped_column(String(200))
    specifier: Mapped[str] = mapped_column(Text)
    extras: Mapped[list[str]] = mapped_column(ARRAY(String(200)))
    marker: Mapped[str | None] = mapped_column(Text)
    url: Mapped[str | None] = mapped_column(Text)
    __table_args__ = (UniqueConstraint("release_id", "raw"),)


class ImportJobRow(Base):
    __tablename__ = "import_jobs"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    request_key: Mapped[UUID] = mapped_column(unique=True)
    status: Mapped[str] = mapped_column(String(16))
    source: Mapped[str] = mapped_column(String(16), default="PYPI")
    processed: Mapped[int] = mapped_column(Integer, default=0)
    checkpoint: Mapped[dict] = mapped_column(JSONB, default=dict)
    error_code: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued','running','succeeded','failed')", name="import_status"
        ),
        CheckConstraint("source = 'PYPI' AND processed >= 0", name="import_source_progress"),
    )
