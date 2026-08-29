from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import (
    DateTime,
    Enum,
    ForeignKey,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.enums import ResourceType
from app.models.mixins import UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.website import Website


class WebsiteGoogleLink(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "website_google_links"
    __table_args__ = (
        UniqueConstraint(
            "website_id", "resource_type", "resource_id", name="website_resource"
        ),
    )

    website_id: Mapped[UUID] = mapped_column(
        ForeignKey("websites.id", ondelete="CASCADE"), nullable=False, index=True
    )
    google_connection_id: Mapped[UUID] = mapped_column(
        ForeignKey("google_connections.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    resource_type: Mapped[ResourceType] = mapped_column(
        Enum(
            ResourceType,
            native_enum=False,
            create_constraint=True,
            name="resource_type",
            length=32,
        ),
        nullable=False,
    )
    resource_id: Mapped[str] = mapped_column(String(255), nullable=False)
    resource_display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    linked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    website: Mapped[Website] = relationship(back_populates="google_links")
