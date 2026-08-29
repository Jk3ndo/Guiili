from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import DateTime, Enum, ForeignKey, Index, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.enums import SnapshotSource
from app.models.mixins import UUIDPrimaryKeyMixin


class AuditSnapshot(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "audit_snapshots"
    __table_args__ = (
        Index("ix_audit_snapshots_website_captured", "website_id", "captured_at"),
    )

    website_id: Mapped[UUID] = mapped_column(
        ForeignKey("websites.id", ondelete="CASCADE"), nullable=False
    )
    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    source: Mapped[SnapshotSource] = mapped_column(
        Enum(SnapshotSource, native_enum=False, create_constraint=True, name="snapshot_source", length=32),
        nullable=False,
    )
    metrics: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
