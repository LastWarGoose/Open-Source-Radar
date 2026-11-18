from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class VulnerabilityRow(Base):
    __tablename__ = "vulnerabilities"
    id: Mapped[str] = mapped_column(String(200), primary_key=True)
    summary: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(32))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AliasRow(Base):
    __tablename__ = "vulnerability_aliases"
    alias: Mapped[str] = mapped_column(String(200), primary_key=True)
    vulnerability_id: Mapped[str] = mapped_column(
        ForeignKey("vulnerabilities.id", ondelete="CASCADE"), index=True
    )


class VersionScanRow(Base):
    __tablename__ = "version_scans"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    release_id: Mapped[str] = mapped_column(String(36), unique=True)
    package_name: Mapped[str | None] = mapped_column(String(200), index=True)
    version: Mapped[str | None] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(16))
    source: Mapped[str] = mapped_column(String(32))
    checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(64))
    __table_args__ = (
        CheckConstraint("status IN ('UNKNOWN','SUCCESS','STALE','FAILED')", name="scan_status"),
        CheckConstraint(
            "status <> 'SUCCESS' OR (checked_at IS NOT NULL AND last_success_at IS NOT NULL)",
            name="success_checked",
        ),
    )


class FindingRow(Base):
    __tablename__ = "scan_findings"
    scan_id: Mapped[UUID] = mapped_column(
        ForeignKey("version_scans.id", ondelete="CASCADE"), primary_key=True
    )
    vulnerability_id: Mapped[str] = mapped_column(
        ForeignKey("vulnerabilities.id", ondelete="CASCADE"), primary_key=True
    )
    fixed_version: Mapped[str | None] = mapped_column(String(200))
