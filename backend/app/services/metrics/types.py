"""Contrat commun des sources de métriques (`MetricSource`) et de leurs observations.

Une observation est `(métrique, jour, valeur, dimensions)` ; le site et la source sont
portés par l'appelant. Une source en erreur lève `SourceError` : elle ne renvoie jamais
une valeur inventée ni un zéro de remplacement."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from app.models.website import Website


def utc_today() -> date:
    return datetime.now(UTC).date()


def utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class DayRange:
    """Fenêtre de jours, bornes incluses."""

    start: date
    end: date

    def __post_init__(self) -> None:
        if self.end < self.start:
            raise ValueError("fenêtre vide : la fin précède le début")

    @property
    def length(self) -> int:
        return (self.end - self.start).days + 1

    def days(self) -> list[date]:
        return [self.start + timedelta(days=offset) for offset in range(self.length)]

    def chunks(self, size: int) -> list[DayRange]:
        if size < 1:
            raise ValueError("le pas de découpage doit être positif")
        parts: list[DayRange] = []
        cursor = self.start
        while cursor <= self.end:
            last = min(cursor + timedelta(days=size - 1), self.end)
            parts.append(DayRange(cursor, last))
            cursor = last + timedelta(days=1)
        return parts

    def contains(self, day: date) -> bool:
        return self.start <= day <= self.end


@dataclass(frozen=True, slots=True)
class Observation:
    metric: str
    day: date
    value: float
    dims: dict[str, str] = field(default_factory=dict)


class SourceError(Exception):
    """Échec typé d'une source.

    - `not_applicable` : rien à collecter (source non reliée, site archivé). La tâche est
      « ignorée », jamais une alerte, jamais retentée.
    - `recoverable` : une nouvelle tentative a du sens (quota, réseau, 5xx, réponse de
      forme inattendue). Sinon l'échec est définitif pour cette exécution (droits, jeton).
    """

    def __init__(self, reason: str, *, recoverable: bool, not_applicable: bool = False) -> None:
        super().__init__(reason)
        self.reason = reason
        self.not_applicable = not_applicable
        self.recoverable = recoverable and not not_applicable


@dataclass(frozen=True, slots=True)
class SourceSpec:
    name: str
    # Source à quota (Google) : plancher de fréquence de 8 h.
    quota_limited: bool
    min_interval: timedelta
    # Retard des données : dernier jour fiable = aujourd'hui - freshness_days.
    freshness_days: int
    # Jours récents recollectés à chaque passage (GA4 révise les 48 dernières heures).
    refresh_days: int
    # Pas de découpage d'une fenêtre (une requête par tranche).
    max_days_per_call: int
    # Rattrapage initial en jours ; 0 = aucun.
    backfill_days: int
    # Dimensions permises (une seule par observation).
    dimensions: tuple[str, ...]

    def _last_day(self, today: date) -> date:
        return today - timedelta(days=self.freshness_days)

    def regular_window(self, today: date) -> DayRange:
        end = self._last_day(today)
        return DayRange(end - timedelta(days=self.refresh_days - 1), end)

    def backfill_window(self, today: date) -> DayRange | None:
        if self.backfill_days <= 0:
            return None
        end = self._last_day(today)
        return DayRange(end - timedelta(days=self.backfill_days - 1), end)


SOURCE_SPECS: dict[str, SourceSpec] = {
    "ga4": SourceSpec(
        name="ga4",
        quota_limited=True,
        min_interval=timedelta(hours=8),
        freshness_days=1,
        refresh_days=3,
        max_days_per_call=31,
        backfill_days=90,
        dimensions=("event_name",),
    ),
    "gsc": SourceSpec(
        name="gsc",
        quota_limited=True,
        min_interval=timedelta(hours=8),
        freshness_days=3,
        refresh_days=3,
        max_days_per_call=31,
        backfill_days=90,
        dimensions=("page", "query"),
    ),
    # PageSpeed a un quota et CrUX n'évolue qu'une fois par jour : plancher de 8 h.
    "cwv": SourceSpec(
        name="cwv",
        quota_limited=True,
        min_interval=timedelta(hours=8),
        freshness_days=0,
        refresh_days=1,
        max_days_per_call=1,
        backfill_days=0,
        dimensions=(),
    ),
    "probe": SourceSpec(
        name="probe",
        quota_limited=False,
        min_interval=timedelta(hours=1),
        freshness_days=0,
        refresh_days=1,
        max_days_per_call=1,
        backfill_days=0,
        dimensions=(),
    ),
}


class MetricSource(Protocol):
    spec: SourceSpec

    async def collect(self, website: Website, day_range: DayRange) -> list[Observation]: ...
