from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    DateTime,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.enums import IssueCategory, IssueSeverity, IssueStatus, pg_enum
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class IssueItem(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "issue_items"
    __table_args__ = (
        UniqueConstraint(
            "website_id", "fingerprint", name="uq_issue_items_website_fingerprint"
        ),
    )

    website_id: Mapped[UUID] = mapped_column(
        ForeignKey("websites.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[IssueCategory] = mapped_column(
        pg_enum(IssueCategory, "issue_category"),
        nullable=False,
    )
    severity: Mapped[IssueSeverity] = mapped_column(
        pg_enum(IssueSeverity, "issue_severity"),
        nullable=False,
    )
    status: Mapped[IssueStatus] = mapped_column(
        pg_enum(IssueStatus, "issue_status"),
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
        ForeignKey("audit_snapshots.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
