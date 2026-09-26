from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from sqlalchemy import (
    DDL,
    Date,
    DateTime,
    Double,
    ForeignKey,
    PrimaryKeyConstraint,
    String,
    Uuid,
    event,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

# Partition « attrape-tout » : une ligne dont le mois n'a pas encore sa partition y
# atterrit au lieu de faire échouer la collecte ; la maintenance l'en sort ensuite.
DEFAULT_PARTITION = "metric_points_default"


class MetricPoint(Base):
    """Série temporelle étroite : une valeur par (site, source, métrique, dimensions, jour).

    Partitionnée par mois sur `day`. La clé primaire porte les cinq colonnes : rejouer
    un jour réécrit les mêmes lignes (idempotence). `dim_key` vaut "" pour le total et
    une empreinte stable des dimensions sinon ; `dims` garde les valeurs lisibles."""

    __tablename__ = "metric_points"
    __table_args__ = (
        PrimaryKeyConstraint("website_id", "source", "metric", "dim_key", "day"),
        {"postgresql_partition_by": "RANGE (day)"},
    )

    website_id: Mapped[UUID] = mapped_column(ForeignKey("websites.id", ondelete="CASCADE"))
    source: Mapped[str] = mapped_column(String(32))
    metric: Mapped[str] = mapped_column(String(64))
    dim_key: Mapped[str] = mapped_column(String(64))
    day: Mapped[date] = mapped_column(Date)
    value: Mapped[float] = mapped_column(Double, nullable=False)
    dims: Mapped[dict[str, str]] = mapped_column(JSONB, nullable=False, default=dict)
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # Exécution (job_runs.id) qui a écrit la ligne. Pas de clé étrangère : l'historique
    # des exécutions est purgé bien avant les points (90 jours contre 25 mois).
    run_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)


# `Base.metadata.create_all` (base des tests) crée la table partitionnée SANS aucune
# partition : sans la partition par défaut, toute insertion échouerait. La migration
# crée elle-même cette partition et les partitions mensuelles.
event.listen(
    MetricPoint.__table__,
    "after_create",
    DDL(f"CREATE TABLE {DEFAULT_PARTITION} PARTITION OF metric_points DEFAULT"),
)
