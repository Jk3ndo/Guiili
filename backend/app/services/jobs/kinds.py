"""Types de tâches, fréquences et identité d'une exécution (`RunSpec`)."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Literal
from uuid import UUID

from app.services.metrics.types import SOURCE_SPECS

Frequency = Literal["hourly", "three_daily", "daily", "every_3_days", "weekly"]
QueueName = Literal["ga4", "gsc", "cwv", "light", "heavy"]

FREQUENCY_INTERVALS: dict[str, timedelta] = {
    "hourly": timedelta(hours=1),
    "three_daily": timedelta(hours=8),
    "daily": timedelta(days=1),
    "every_3_days": timedelta(days=3),
    "weekly": timedelta(days=7),
}
FREQUENCY_LABELS: dict[str, str] = {
    "hourly": "Toutes les heures",
    "three_daily": "3 fois par jour",
    "daily": "Tous les jours",
    "every_3_days": "Tous les 3 jours",
    "weekly": "Toutes les semaines",
}

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


@dataclass(frozen=True, slots=True)
class TaskKind:
    name: str
    label: str
    queue: QueueName = "light"
    schedulable: bool = False
    # Source collectée (tâches `collect_*`).
    source: str | None = None
    # Plancher de fréquence (quotas Google : 8 h ; sondes légères : 1 h).
    floor: timedelta = timedelta(hours=1)
    default_frequency: Frequency | None = None
    per_site: bool = True

    def allowed_frequencies(self) -> tuple[str, ...]:
        return tuple(name for name, interval in FREQUENCY_INTERVALS.items() if interval >= self.floor)


KINDS: dict[str, TaskKind] = {
    kind.name: kind
    for kind in (
        TaskKind(
            "collect_ga4", "Données Google Analytics 4", queue="ga4", schedulable=True,
            source="ga4", floor=SOURCE_SPECS["ga4"].min_interval, default_frequency="daily",
        ),
        TaskKind(
            "collect_gsc", "Données Search Console", queue="gsc", schedulable=True,
            source="gsc", floor=SOURCE_SPECS["gsc"].min_interval, default_frequency="daily",
        ),
        TaskKind(
            "collect_cwv", "Core Web Vitals des visiteurs réels", queue="cwv",
            schedulable=True, source="cwv", floor=SOURCE_SPECS["cwv"].min_interval,
            default_frequency="daily",
        ),
        TaskKind(
            "collect_probes", "Certificat HTTPS et disponibilité du site", queue="light",
            schedulable=True, source="probe", floor=SOURCE_SPECS["probe"].min_interval,
            default_frequency="three_daily",
        ),
        # Lit GA4 et Search Console : même plancher que les sources à quota.
        TaskKind(
            "measurement_check", "Vérification du plan de mesure", queue="light",
            schedulable=True, floor=timedelta(hours=8), default_frequency="daily",
        ),
        TaskKind("backfill", "Historique initial (90 jours)"),
        TaskKind("partition_maintenance", "Maintenance du stockage des mesures", per_site=False),
    )
}
SCHEDULABLE_KINDS: tuple[TaskKind, ...] = tuple(k for k in KINDS.values() if k.schedulable)
BACKFILL_SOURCES: tuple[str, ...] = ("ga4", "gsc")
COLLECT_KIND_BY_SOURCE: dict[str, str] = {
    kind.source: kind.name for kind in SCHEDULABLE_KINDS if kind.source is not None
}


def effective_interval(kind: TaskKind, frequency: str) -> timedelta:
    return max(FREQUENCY_INTERVALS[frequency], kind.floor)


def schedule_offset(schedule_id: UUID, interval: timedelta) -> timedelta:
    """Décalage stable de CE planning dans `[0, interval)`.

    Sans lui, tous les plannings « tous les jours » retombent à minuit UTC pile (grille
    Unix) et lancent leurs collectes Google en même temps. Dérivé de l'identifiant du
    planning : deux sources d'un même site se décalent aussi l'une de l'autre."""
    digest = hashlib.sha256(schedule_id.bytes).digest()
    return interval * (int.from_bytes(digest[:8], "big") / 2**64)


def slot_start(now: datetime, interval: timedelta, *, offset: timedelta = timedelta(0)) -> datetime:
    """Début du créneau contenant `now` (grille Unix en UTC décalée de `offset`)."""
    anchor = _EPOCH + offset
    return anchor + ((now - anchor) // interval) * interval


def slot_label(slot: datetime) -> str:
    return slot.astimezone(UTC).strftime("%Y%m%dT%H%M")


@dataclass(frozen=True, slots=True)
class RunSpec:
    """Identité d'une exécution : la clé d'idempotence en découle."""

    kind: str
    website_id: UUID | None
    workspace_id: UUID | None
    window: str
    params: dict[str, str] = field(default_factory=dict)

    @property
    def key(self) -> str:
        return f"{self.kind}:{self.website_id or 'global'}:{self.window}"

    @property
    def queue(self) -> QueueName:
        if self.kind == "backfill":
            source = self.params.get("source")
            return "gsc" if source == "gsc" else "ga4" if source == "ga4" else "light"
        return KINDS[self.kind].queue

    def to_payload(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "website_id": str(self.website_id) if self.website_id else None,
            "workspace_id": str(self.workspace_id) if self.workspace_id else None,
            "window": self.window,
            "params": dict(self.params),
        }
