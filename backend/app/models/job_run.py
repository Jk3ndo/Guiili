from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.mixins import UUIDPrimaryKeyMixin


class JobRun(UUIDPrimaryKeyMixin, Base):
    """Une exécution de tâche. `idempotency_key` = « type:site:fenêtre » : deux
    livraisons de la même tâche partagent la même ligne. Le bail (`lease_expires_at`)
    libère une tâche dont le worker est mort. Source des alertes d'exploitation."""

    __tablename__ = "job_runs"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_job_runs_idempotency_key"),
        Index("ix_job_runs_status_lease", "status", "lease_expires_at"),
        Index("ix_job_runs_workspace_enqueued", "workspace_id", "enqueued_at"),
        Index("ix_job_runs_website_kind_enqueued", "website_id", "kind", "enqueued_at"),
    )

    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    # Null pour les tâches globales (maintenance des partitions).
    website_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("websites.id", ondelete="CASCADE"), nullable=True
    )
    workspace_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=True
    )
    window_label: Mapped[str] = mapped_column(String(40), nullable=False)
    params: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    enqueued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Code stable (jamais un message d'exception, jamais un jeton).
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Nom de classe d'une exception inattendue, pour le diagnostic.
    error_detail: Mapped[str | None] = mapped_column(String(300), nullable=True)
    recoverable: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    observations: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
