from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import (
    ARRAY,
    DateTime,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.enums import ConnectionStatus, pg_enum
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.user import User


class GoogleConnection(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "google_connections"
    __table_args__ = (
        # un utilisateur ne lie pas deux fois la même identité Google
        UniqueConstraint(
            "user_id", "google_sub", name="uq_google_connections_user_google_sub"
        ),
    )

    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    google_account_email: Mapped[str] = mapped_column(String(320), nullable=False)
    google_sub: Mapped[str] = mapped_column(String(255), nullable=False)
    granted_scopes: Mapped[list[str]] = mapped_column(
        ARRAY(String), nullable=False
    )
    refresh_token_encrypted: Mapped[bytes] = mapped_column(
        LargeBinary, nullable=False
    )
    encryption_key_version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[ConnectionStatus] = mapped_column(
        pg_enum(ConnectionStatus, "connection_status"),
        nullable=False,
        default=ConnectionStatus.ACTIVE,
    )
    last_refreshed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    user: Mapped[User] = relationship(back_populates="google_connections")
