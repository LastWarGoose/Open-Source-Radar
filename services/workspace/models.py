from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class ActorRow(Base):
    __tablename__ = "actors"
    id: Mapped[UUID] = mapped_column(primary_key=True)


class AccountRow(Base):
    __tablename__ = "accounts"
    actor_id: Mapped[UUID] = mapped_column(ForeignKey("actors.id"), primary_key=True)
    username: Mapped[str] = mapped_column(String(40), unique=True)
    password_hash: Mapped[str] = mapped_column(Text)
    recovery_hash: Mapped[str] = mapped_column(String(64))
    role: Mapped[str] = mapped_column(String(10), default="user")


class SessionRow(Base):
    __tablename__ = "sessions"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    actor_id: Mapped[UUID] = mapped_column(ForeignKey("accounts.actor_id"), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class AuthAttemptRow(Base):
    __tablename__ = "auth_attempts"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    attempts: Mapped[int] = mapped_column(default=0)
    reset_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class FollowRow(Base):
    __tablename__ = "follows"
    owner_id: Mapped[UUID] = mapped_column(ForeignKey("actors.id"), primary_key=True)
    package_id: Mapped[str] = mapped_column(String(220), primary_key=True)
    version: Mapped[str | None] = mapped_column(String(200))
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class CollectionRow(Base):
    __tablename__ = "collections"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    owner_id: Mapped[UUID] = mapped_column(ForeignKey("actors.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (UniqueConstraint("owner_id", "name"),)


class CollectionItemRow(Base):
    __tablename__ = "collection_items"
    collection_id: Mapped[UUID] = mapped_column(
        ForeignKey("collections.id", ondelete="CASCADE"), primary_key=True
    )
    package_id: Mapped[str] = mapped_column(String(220), primary_key=True)


class NotificationRow(Base):
    __tablename__ = "notifications"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    owner_id: Mapped[UUID] = mapped_column(ForeignKey("actors.id"), index=True)
    message: Mapped[str] = mapped_column(Text)
    package_id: Mapped[str | None] = mapped_column(String(220))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
