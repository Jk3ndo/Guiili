from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class WorkspaceInvitation(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "workspace_invitations"

    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    invited_email: Mapped[str] = mapped_column(String(320), nullable=False)
    token: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    invited_by_user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="pending", server_default="pending"
    )  # "pending" | "accepted" | "revoked" | "expired"
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
