from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class Schedule(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Planning d'un type de tâche pour un site : fréquence choisie, prochaine échéance,
    dernier passage. `kind` et `frequency` sont des chaînes validées par le code
    (`app.services.jobs.kinds`)."""

    __tablename__ = "schedules"
    __table_args__ = (
        UniqueConstraint("website_id", "kind", name="uq_schedules_website_kind"),
        Index("ix_schedules_next_due_at", "next_due_at"),
    )

    website_id: Mapped[UUID] = mapped_column(
        ForeignKey("websites.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    frequency: Mapped[str] = mapped_column(String(16), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    next_due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Statut du dernier job_run terminé (succeeded | failed | skipped).
    last_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    last_success_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Début de la série d'échecs en cours (vidé au premier succès) : source des alertes.
    failing_since: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Rattrapage initial (90 jours) réussi : les passages suivants ne collectent que
    # les jours récents.
    backfill_done_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
