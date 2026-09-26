"""Stockage idempotent des observations et recalcul des cumuls.

Règles :
- une observation hors registre, avec une dimension non permise, une valeur de
  dimension écartée par le nettoyage ou une valeur non finie est ignorée (et comptée) ;
  elle n'est jamais stockée comme ligne « total » ;
- le nettoyage peut faire converger plusieurs observations vers la même clé (métrique,
  dimension, jour) : elles sont fusionnées selon l'agrégation de la métrique (somme pour
  les métriques additives), jamais écrasées ;
- chaque dimension est plafonnée à `top_n` valeurs par jour (les plus fortes) ;
- rejouer un jour remplace exactement les lignes de ce couple (métrique, jour) : un
  même jeu d'observations donne toujours les mêmes lignes ; un jour absent de la
  collecte n'est jamais effacé ;
- le verrou (site, source) est pris AVANT toute lecture ou écriture.
Aucune fonction ne committe : l'appelant décide de la transaction."""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from statistics import fmean
from typing import Any
from uuid import UUID

from sqlalchemy import delete, insert, select, text, tuple_
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.metric_point import MetricPoint
from app.models.metric_rollup import MetricRollup
from app.services.metrics.aggregate import (
    GRAINS,
    aggregate,
    period_end,
    period_start,
    siblings_needed,
)
from app.services.metrics.dimensions import CLEANERS, dim_key
from app.services.metrics.registry import MetricDef, metric_def
from app.services.metrics.types import Observation

_BATCH = 1000
_POINT_KEY = ["website_id", "source", "metric", "dim_key", "day"]


@dataclass(frozen=True, slots=True)
class StoreResult:
    written: int
    dropped: int
    days: frozenset[date]


async def lock_metrics(session: AsyncSession, website_id: UUID, source: str) -> None:
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:key))"),
        {"key": f"metrics:{website_id}:{source}"},
    )


def _batches(rows: list[dict[str, Any]]) -> Iterator[list[dict[str, Any]]]:
    for index in range(0, len(rows), _BATCH):
        yield rows[index : index + _BATCH]


def _rank(row: dict[str, Any]) -> tuple[float, str]:
    """Valeur décroissante, puis valeur de dimension croissante (ordre déterministe)."""
    return (-row["value"], next(iter(row["dims"].values())))


def _clean_dims(defn: MetricDef, dims: dict[str, str]) -> dict[str, str] | None:
    if not dims:
        return {}
    if len(dims) != 1:
        return None
    ((name, raw),) = dims.items()
    if name not in defn.dimensions or not isinstance(raw, str):
        return None
    cleaned = CLEANERS[name](raw)
    return {name: cleaned} if cleaned is not None else None


def _merge(defn: MetricDef, values: list[float]) -> float:
    """Fusionne des valeurs qui convergent vers la même clé : somme pour une métrique
    additive, moyenne pour une moyenne, sinon la dernière valeur reçue."""
    if defn.aggregation == "sum":
        return math.fsum(values)
    if defn.aggregation == "mean":
        return fmean(values)
    return values[-1]


def prepare_rows(
    *,
    website_id: UUID,
    source: str,
    observations: Sequence[Observation],
    run_id: UUID | None,
    now: datetime,
) -> tuple[list[dict[str, Any]], int]:
    dropped = 0
    collected: dict[tuple[str, str, date], tuple[MetricDef, dict[str, str], list[float]]] = {}
    for obs in observations:
        defn = metric_def(source, obs.metric)
        value = obs.value
        if (
            defn is None
            or isinstance(value, bool)
            or not isinstance(value, int | float)
            or not math.isfinite(value)
        ):
            dropped += 1
            continue
        dims = _clean_dims(defn, obs.dims)
        if dims is None:
            dropped += 1
            continue
        entry = collected.setdefault((obs.metric, dim_key(dims), obs.day), (defn, dims, []))
        entry[2].append(float(value))

    rows: list[dict[str, Any]] = []
    groups: dict[tuple[str, str, date], tuple[MetricDef, list[dict[str, Any]]]] = {}
    for (metric, key, day), (defn, dims, values) in collected.items():
        merged = _merge(defn, values)
        if not math.isfinite(merged):
            dropped += 1
            continue
        row = {
            "website_id": website_id,
            "source": source,
            "metric": metric,
            "dim_key": key,
            "day": day,
            "value": merged,
            "dims": dims,
            "collected_at": now,
            "run_id": run_id,
        }
        if not dims:
            rows.append(row)
            continue
        name = next(iter(dims))
        groups.setdefault((metric, name, day), (defn, []))[1].append(row)
    for defn, members in groups.values():
        members.sort(key=_rank)
        rows.extend(members[: defn.top_n])
        dropped += max(0, len(members) - defn.top_n)
    rows.sort(key=lambda r: (r["metric"], r["day"], r["dim_key"]))
    return rows, dropped


async def store_observations(
    session: AsyncSession,
    *,
    website_id: UUID,
    source: str,
    observations: Sequence[Observation],
    run_id: UUID | None,
    now: datetime,
) -> StoreResult:
    rows, dropped = prepare_rows(
        website_id=website_id, source=source, observations=observations, run_id=run_id, now=now
    )
    if not rows:
        return StoreResult(written=0, dropped=dropped, days=frozenset())
    await lock_metrics(session, website_id, source)
    pairs = sorted({(row["metric"], row["day"]) for row in rows})
    await session.execute(
        delete(MetricPoint).where(
            MetricPoint.website_id == website_id,
            MetricPoint.source == source,
            tuple_(MetricPoint.metric, MetricPoint.day).in_(pairs),
        )
    )
    for chunk in _batches(rows):
        statement = pg_insert(MetricPoint).values(chunk)
        statement = statement.on_conflict_do_update(
            index_elements=_POINT_KEY,
            set_={
                "value": statement.excluded.value,
                "dims": statement.excluded.dims,
                "collected_at": statement.excluded.collected_at,
                "run_id": statement.excluded.run_id,
            },
        )
        await session.execute(statement)
    days = frozenset(day for _, day in pairs)
    await refresh_rollups(session, website_id=website_id, source=source, days=days, now=now)
    return StoreResult(written=len(rows), dropped=dropped, days=days)


async def refresh_rollups(
    session: AsyncSession,
    *,
    website_id: UUID,
    source: str,
    days: Iterable[date],
    now: datetime,
) -> int:
    """Recalcule entièrement les cumuls des semaines et mois touchés par `days`, à partir
    de tous les points de ces périodes (idempotent : supprimer puis réécrire)."""
    wanted = set(days)
    if not wanted:
        return 0
    written = 0
    for grain in GRAINS:
        starts = sorted({period_start(day, grain) for day in wanted})
        start_set = set(starts)
        low, high = starts[0], period_end(starts[-1], grain)
        result = await session.execute(
            select(
                MetricPoint.metric, MetricPoint.dim_key, MetricPoint.day, MetricPoint.value,
                MetricPoint.dims,
            ).where(
                MetricPoint.website_id == website_id,
                MetricPoint.source == source,
                MetricPoint.day >= low,
                MetricPoint.day <= high,
            )
        )
        series: dict[tuple[str, str, date], dict[date, float]] = defaultdict(dict)
        labels: dict[tuple[str, date], dict[str, str]] = {}
        for metric, key, day, value, dims in result.all():
            start = period_start(day, grain)
            if start not in start_set:
                continue
            series[(metric, key, start)][day] = value
            labels[(key, start)] = dims
        await session.execute(
            delete(MetricRollup).where(
                MetricRollup.website_id == website_id,
                MetricRollup.source == source,
                MetricRollup.grain == grain,
                MetricRollup.period_start.in_(starts),
            )
        )
        rows: list[dict[str, Any]] = []
        for (metric, key, start), values in series.items():
            defn = metric_def(source, metric)
            if defn is None:
                continue
            # Ratios et moyennes pondérées : seules les séries TOTALES servent de base.
            siblings = {name: series.get((name, "", start), {}) for name in siblings_needed(defn)}
            value = aggregate(defn, values, siblings)
            if value is None or not math.isfinite(value):
                continue
            rows.append(
                {
                    "website_id": website_id,
                    "source": source,
                    "metric": metric,
                    "dim_key": key,
                    "grain": grain,
                    "period_start": start,
                    "value": value,
                    "days_covered": len(values),
                    "dims": labels[(key, start)],
                    "updated_at": now,
                }
            )
        for chunk in _batches(rows):
            await session.execute(insert(MetricRollup).values(chunk))
        written += len(rows)
    return written
