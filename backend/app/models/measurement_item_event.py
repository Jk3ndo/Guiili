from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.mixins import UUIDPrimaryKeyMixin


class MeasurementItemEvent(UUIDPrimaryKeyMixin, Base):
    """Historique : une ligne à chaque changement d'état d'un item du plan de mesure
    (permet de tracer l'avancement dans le temps). L'état courant reste dans
    `measurement_item_statuses`."""

    __tablename__ = "measurement_item_events"
    __table_args__ = (
        Index("ix_measurement_item_events_site_item_at", "website_id", "item_id", "at"),
    )

    website_id: Mapped[UUID] = mapped_column(
        ForeignKey("websites.id", ondelete="CASCADE"), nullable=False
    )
    item_id: Mapped[str] = mapped_column(String(64), nullable=False)
    # None pour la toute première observation d'un item.
    from_state: Mapped[str | None] = mapped_column(String(32), nullable=True)
    to_state: Mapped[str] = mapped_column(String(32), nullable=False)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    evidence: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
