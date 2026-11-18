from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class RepositoryRow(Base):
    __tablename__ = "repositories"
    id: Mapped[str] = mapped_column(String(250), primary_key=True)
    full_name: Mapped[str] = mapped_column(String(220), unique=True)
    description: Mapped[str | None] = mapped_column(Text)
    url: Mapped[str] = mapped_column(String(300), unique=True)
    stars: Mapped[int] = mapped_column(Integer)
    source: Mapped[str] = mapped_column(String(32))
    source_id: Mapped[str] = mapped_column(String(250), unique=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    __table_args__ = (CheckConstraint("stars >= 0", name="nonnegative_stars"),)


class PackageRepositoryRow(Base):
    __tablename__ = "package_repositories"
    package_id: Mapped[str] = mapped_column(String(220), primary_key=True)
    repository_id: Mapped[str] = mapped_column(
        ForeignKey("repositories.id", ondelete="CASCADE"), primary_key=True
    )
    status: Mapped[str] = mapped_column(String(16))
    __table_args__ = (
        CheckConstraint("status IN ('UNVERIFIED','VERIFIED','INVALID')", name="link_status"),
    )
