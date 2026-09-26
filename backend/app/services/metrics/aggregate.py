"""Agrégation pure d'une série journalière selon le registre (cumuls semaine/mois,
totaux de l'API de séries). Aucune période sans donnée ne produit de valeur : None."""

from __future__ import annotations

import calendar
from collections.abc import Mapping
from datetime import date, timedelta
from statistics import fmean
from typing import Literal

from app.services.metrics.registry import MetricDef

Grain = Literal["week", "month"]
GRAINS: tuple[Grain, ...] = ("week", "month")


def week_start(day: date) -> date:
    return day - timedelta(days=day.weekday())


def month_start(day: date) -> date:
    return day.replace(day=1)


def period_start(day: date, grain: Grain) -> date:
    return week_start(day) if grain == "week" else month_start(day)


def period_end(start: date, grain: Grain) -> date:
    if grain == "week":
        return start + timedelta(days=6)
    return start.replace(day=calendar.monthrange(start.year, start.month)[1])


def periods_between(start: date, end: date, grain: Grain) -> list[date]:
    periods: list[date] = []
    cursor = period_start(start, grain)
    while cursor <= end:
        periods.append(cursor)
        cursor = period_end(cursor, grain) + timedelta(days=1)
    return periods


def siblings_needed(defn: MetricDef) -> tuple[str, ...]:
    if defn.aggregation == "ratio" and defn.ratio_of is not None:
        return defn.ratio_of
    if defn.aggregation == "weighted_mean" and defn.weight_by is not None:
        return (defn.weight_by,)
    return ()


def aggregate(
    defn: MetricDef,
    values: Mapping[date, float],
    siblings: Mapping[str, Mapping[date, float]] | None = None,
) -> float | None:
    siblings = siblings or {}
    if defn.aggregation == "sum":
        return float(sum(values.values())) if values else None
    if defn.aggregation == "mean":
        return fmean(values.values()) if values else None
    if defn.aggregation == "last":
        return float(values[max(values)]) if values else None
    if defn.aggregation == "ratio" and defn.ratio_of is not None:
        numerator = siblings.get(defn.ratio_of[0], {})
        denominator = siblings.get(defn.ratio_of[1], {})
        days = numerator.keys() & denominator.keys()
        total = sum(denominator[day] for day in days)
        if not days or total == 0:
            return None
        return sum(numerator[day] for day in days) / total
    if defn.aggregation == "weighted_mean" and defn.weight_by is not None:
        weights = siblings.get(defn.weight_by, {})
        days = values.keys() & weights.keys()
        total = sum(weights[day] for day in days)
        if not days or total == 0:
            return None
        return sum(values[day] * weights[day] for day in days) / total
    return None
