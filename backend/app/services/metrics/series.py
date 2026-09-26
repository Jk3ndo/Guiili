"""Lecture unique des séries temporelles (tableau de bord, rapports, conseiller).

Semaines et mois entièrement compris dans la période : lus dans `metric_rollups`
(pré-calculés). Périodes coupées par les bornes et granularité journalière : calculées
depuis `metric_points` avec la même agrégation que les cumuls. Une période sans aucune
donnée vaut `None` (jamais zéro) ; `days_covered` / `days_expected` disent si elle est
complète."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Literal, NamedTuple
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.metric_point import MetricPoint
from app.models.metric_rollup import MetricRollup
from app.services.metrics.aggregate import aggregate, period_end, periods_between, siblings_needed
from app.services.metrics.registry import MetricDef
from app.services.metrics.types import DayRange

Granularity = Literal["day", "week", "month"]
Compare = Literal["none", "previous_period", "previous_year"]
MAX_RANGE_DAYS = 800
DEFAULT_RANGE_DAYS = 28


@dataclass(frozen=True, slots=True)
class SeriesPoint:
    period_start: date
    period_end: date
    value: float | None
    days_covered: int
    days_expected: int


@dataclass(frozen=True, slots=True)
class Series:
    start: date
    end: date
    points: tuple[SeriesPoint, ...]
    total: float | None


class Freshness(NamedTuple):
    last_collected_at: datetime | None
    data_until: date | None


def shift_year(day: date) -> date:
    try:
        return day.replace(year=day.year - 1)
    except ValueError:  # 29 février
        return day.replace(year=day.year - 1, day=28)


def comparison_range(start: date, end: date, compare: str) -> tuple[date, date] | None:
    if compare == "previous_period":
        length = (end - start).days + 1
        return start - timedelta(days=length), start - timedelta(days=1)
    if compare == "previous_year":
        return shift_year(start), shift_year(end)
    return None


async def _load_daily(
    session: AsyncSession, website_id: UUID, defn: MetricDef, start: date, end: date
) -> dict[str, dict[date, float]]:
    names = (defn.name, *siblings_needed(defn))
    rows = await session.execute(
        select(MetricPoint.metric, MetricPoint.day, MetricPoint.value).where(
            MetricPoint.website_id == website_id,
            MetricPoint.source == defn.source,
            MetricPoint.metric.in_(names),
            MetricPoint.dim_key == "",
            MetricPoint.day >= start,
            MetricPoint.day <= end,
        )
    )
    daily: dict[str, dict[date, float]] = {name: {} for name in names}
    for metric, day, value in rows.all():
        daily[metric][day] = value
    return daily


async def _load_rollups(
    session: AsyncSession, website_id: UUID, defn: MetricDef, grain: str, starts: list[date]
) -> dict[date, tuple[float, int]]:
    if not starts:
        return {}
    rows = await session.execute(
        select(MetricRollup.period_start, MetricRollup.value, MetricRollup.days_covered).where(
            MetricRollup.website_id == website_id,
            MetricRollup.source == defn.source,
            MetricRollup.metric == defn.name,
            MetricRollup.dim_key == "",
            MetricRollup.grain == grain,
            MetricRollup.period_start.in_(starts),
        )
    )
    return {start: (value, covered) for start, value, covered in rows.all()}


def _within(series: dict[date, float], low: date, high: date) -> dict[date, float]:
    return {day: value for day, value in series.items() if low <= day <= high}


async def build_series(
    session: AsyncSession,
    *,
    website_id: UUID,
    defn: MetricDef,
    start: date,
    end: date,
    granularity: str,
) -> Series:
    daily = await _load_daily(session, website_id, defn, start, end)
    values = daily[defn.name]
    siblings = {name: daily[name] for name in siblings_needed(defn)}
    total = aggregate(defn, values, siblings)
    points: list[SeriesPoint] = []
    if granularity == "day":
        for day in DayRange(start, end).days():
            points.append(SeriesPoint(day, day, values.get(day), 1 if day in values else 0, 1))
        return Series(start, end, tuple(points), total)

    grain = "week" if granularity == "week" else "month"
    starts = periods_between(start, end, grain)
    full = [s for s in starts if s >= start and period_end(s, grain) <= end]
    stored = await _load_rollups(session, website_id, defn, grain, full)
    for period in starts:
        low, high = max(period, start), min(period_end(period, grain), end)
        expected = (high - low).days + 1
        if period in stored:
            value, covered = stored[period]
        else:
            window = _within(values, low, high)
            window_siblings = {name: _within(series, low, high) for name, series in siblings.items()}
            value = aggregate(defn, window, window_siblings)
            covered = len(window)
        points.append(SeriesPoint(period, period_end(period, grain), value, covered, expected))
    return Series(start, end, tuple(points), total)


async def freshness(session: AsyncSession, website_id: UUID, source: str) -> Freshness:
    row = (
        await session.execute(
            select(func.max(MetricPoint.collected_at), func.max(MetricPoint.day)).where(
                MetricPoint.website_id == website_id, MetricPoint.source == source
            )
        )
    ).one()
    return Freshness(row[0], row[1])
