from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.user import User
    from app.models.website_google_link import WebsiteGoogleLink


class Website(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "websites"
    __table_args__ = (UniqueConstraint("user_id", "domain", name="user_domain"),)

    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    domain: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)

    user: Mapped[User] = relationship(back_populates="websites")
    google_links: Mapped[list[WebsiteGoogleLink]] = relationship(
        back_populates="website", cascade="all, delete-orphan", passive_deletes=True
    )
