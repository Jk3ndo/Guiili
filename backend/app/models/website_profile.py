from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class WebsiteProfile(Base):
    """Profil de mesure d'un site : types détectés / confirmés, réglages du plan,
    dernier résultat du navigateur headless. Une ligne par site."""

    __tablename__ = "website_profiles"

    website_id: Mapped[UUID] = mapped_column(
        ForeignKey("websites.id", ondelete="CASCADE"), primary_key=True
    )
    # [{"type": "ecommerce", "confidence": 0.8, "signals": ["..."]}, ...]
    detected_types: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list
    )
    # Types validés par le propriétaire ; prime sur `detected_types`.
    confirmed_types: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # ga4_measurement_id, ads_conversion_id, ads_conversion_label, uses_google_ads
    params: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    headless_result: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    headless_checked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
