from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.google_connection import GoogleConnection
    from app.models.website import Website


class User(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False)
    auth_provider: Mapped[str] = mapped_column(
        String(32), nullable=False, default="google"
    )
    google_sub: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)

    google_connections: Mapped[list[GoogleConnection]] = relationship(
        back_populates="user", cascade="all, delete-orphan", passive_deletes=True
    )
    websites: Mapped[list[Website]] = relationship(
        back_populates="user", cascade="all, delete-orphan", passive_deletes=True
    )
