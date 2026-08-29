from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    DateTime,
    Enum,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.enums import IssueCategory, IssueSeverity, IssueStatus
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class IssueItem(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "issue_items"
    __table_args__ = (
        UniqueConstraint("website_id", "fingerprint", name="website_fingerprint"),
    )

    website_id: Mapped[UUID] = mapped_column(
        ForeignKey("websites.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[IssueCategory] = mapped_column(
        Enum(IssueCategory, native_enum=False, create_constraint=True, name="issue_category", length=32),
        nullable=False,
    )
    severity: Mapped[IssueSeverity] = mapped_column(
        Enum(IssueSeverity, native_enum=False, create_constraint=True, name="issue_severity", length=32),
        nullable=False,
    )
    status: Mapped[IssueStatus] = mapped_column(
        Enum(IssueStatus, native_enum=False, create_constraint=True, name="issue_status", length=32),
        nullable=False,
        default=IssueStatus.TODO,
    )
    fingerprint: Mapped[str] = mapped_column(String(255), nullable=False)
    detected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    source_snapshot_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("audit_snapshots.id", ondelete="SET NULL"), nullable=True
    )
