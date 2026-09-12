"""Tables de l'agent conseiller : fils de discussion, messages, quota, persona.

`role` / `status` sont des `String` simples (valeurs 100 % controlees par le
code, jamais saisies) — pas de `pg_enum`, pas de `CheckConstraint`.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Date, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.mixins import UUIDPrimaryKeyMixin


class AdvisorThread(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "advisor_threads"

    website_id: Mapped[UUID] = mapped_column(
        ForeignKey("websites.id", ondelete="CASCADE"), nullable=False, index=True
    )
    persona_key: Mapped[str] = mapped_column(String(32), nullable=False)
    custom_prompt_snapshot: Mapped[str | None] = mapped_column(Text, nullable=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    source_snapshot_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("audit_snapshots.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AdvisorMessage(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "advisor_messages"

    thread_id: Mapped[UUID] = mapped_column(
        ForeignKey("advisor_threads.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)  # user | assistant
    blocks: Mapped[list[Any]] = mapped_column(JSONB, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    usage: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False)  # complete | error
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class AdvisorToolCall(UUIDPrimaryKeyMixin, Base):
    """Une ligne par appel d'outil d'action, pour le rate-limit par fil (fenetre glissante)."""

    __tablename__ = "advisor_tool_calls"

    thread_id: Mapped[UUID] = mapped_column(
        ForeignKey("advisor_threads.id", ondelete="CASCADE"), nullable=False, index=True
    )
    tool: Mapped[str] = mapped_column(String(32), nullable=False)
    called_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class AdvisorUsage(Base):
    __tablename__ = "advisor_usage"

    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), primary_key=True
    )
    day: Mapped[date] = mapped_column(Date, primary_key=True)
    brief_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    message_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )


class UserAdvisorSettings(Base):
    __tablename__ = "user_advisor_settings"

    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    persona_key: Mapped[str] = mapped_column(
        String(32), nullable=False, default="consultant", server_default="consultant"
    )
    custom_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
