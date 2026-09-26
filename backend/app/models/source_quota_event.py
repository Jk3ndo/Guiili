from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.mixins import UUIDPrimaryKeyMixin


class SourceQuotaEvent(UUIDPrimaryKeyMixin, Base):
    """Un échec `quota` d'une source Google pour un workspace. Historique EN AJOUT SEUL :
    contrairement à `job_runs` (une ligne par clé d'idempotence, réécrite à chaque
    tentative), aucun événement n'est jamais modifié, ce qui rend le décompte du
    disjoncteur fiable. Purgé au-delà de quelques jours par la maintenance."""

    __tablename__ = "source_quota_events"
    __table_args__ = (
        Index("ix_source_quota_events_workspace_source_at", "workspace_id", "source", "at"),
    )

    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
