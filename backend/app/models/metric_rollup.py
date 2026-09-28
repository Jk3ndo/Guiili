from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from sqlalchemy import Date, DateTime, Double, ForeignKey, Integer, PrimaryKeyConstraint, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class MetricRollup(Base):
    """Cumul d'une série sur une semaine (lundi) ou un mois (le 1er), recalculé après
    chaque collecte. `days_covered` = nombre de jours ayant une valeur dans la période :
    un cumul partiel se voit, il n'est jamais présenté comme complet."""

    __tablename__ = "metric_rollups"
    __table_args__ = (
        PrimaryKeyConstraint(
            "website_id", "source", "metric", "dim_key", "grain", "period_start"
        ),
    )

    website_id: Mapped[UUID] = mapped_column(ForeignKey("websites.id", ondelete="CASCADE"))
    source: Mapped[str] = mapped_column(String(32))
    metric: Mapped[str] = mapped_column(String(64))
    dim_key: Mapped[str] = mapped_column(String(64))
    grain: Mapped[str] = mapped_column(String(8))
    period_start: Mapped[date] = mapped_column(Date)
    value: Mapped[float] = mapped_column(Double, nullable=False)
    days_covered: Mapped[int] = mapped_column(Integer, nullable=False)
    dims: Mapped[dict[str, str]] = mapped_column(JSONB, nullable=False, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
