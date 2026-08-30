from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.mixins import UUIDPrimaryKeyMixin


class OAuthState(UUIDPrimaryKeyMixin, Base):
    """Transaction OAuth éphémère et à usage unique.

    Crée par `/auth/google/start`, consommée (supprimée) par le callback.
    `code_verifier` PKCE ne vaut rien sans le code d'autorisation associé et la
    ligne vit `oauth_state_ttl_seconds` — stocké en clair, jamais réutilisé.
    """

    __tablename__ = "oauth_states"

    state: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    code_verifier: Mapped[str] = mapped_column(String(128), nullable=False)
    # Défini uniquement pour le flux "ajouter un compte" (utilisateur déjà loggé).
    user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=True
    )
    redirect_to: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
