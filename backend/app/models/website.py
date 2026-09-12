from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import Boolean, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.enums import StackKind, pg_enum
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.website_google_link import WebsiteGoogleLink


class Website(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "websites"
    __table_args__ = (
        UniqueConstraint("workspace_id", "domain", name="uq_websites_workspace_domain"),
    )

    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    domain: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    # Renseigne par le moteur d'audit au premier scan ; null tant qu'inconnu.
    detected_stack: Mapped[StackKind | None] = mapped_column(
        pg_enum(StackKind, "stack_kind"), nullable=True
    )
    # Stack saisie / confirmee par l'utilisateur (texte libre : preset ou « Autre »).
    # Prime sur `detected_stack` a l'affichage.
    stack_label: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # Sonder le site en ignorant les erreurs de certificat TLS (choix explicite).
    allow_insecure_probe: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Etat du certificat HTTPS, rafraichi a chaque scan / check a la demande.
    ssl_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    ssl_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ssl_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Site archive : exclu des listes, conserve pour l'historique (purge explicite).
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    google_links: Mapped[list[WebsiteGoogleLink]] = relationship(
        back_populates="website", cascade="all, delete-orphan", passive_deletes=True
    )
