"""Partitions mensuelles de `metric_points`.

- `ensure_partitions` crée d'avance les mois manquants autour d'aujourd'hui. Si des
  lignes de ce mois attendent dans la partition par défaut, PostgreSQL refuse de créer
  la partition (« updated partition constraint for default partition would be violated
  ») : on crée donc une table vide de même forme, on y déplace ces lignes, puis on
  l'attache. La partition par défaut est verrouillée pendant l'opération, ce qui
  empêche une collecte concurrente d'y écrire une ligne du même mois entre-temps.
  Chaque mois est créé dans un point de sauvegarde : si une étape échoue, la table
  intermédiaire est annulée avec le reste (jamais de table orpheline qui ferait
  échouer une migration ultérieure).
- `purge_expired` détache et supprime les partitions entièrement plus vieilles que la
  rétention (25 mois, comparaison annuelle), et purge la partition par défaut au-delà.
  Seul ce qui est prouvé hors rétention est supprimé : une partition n'est retirée que
  si sa borne de fin (exclue) est antérieure ou égale à la limite.
Les noms de tables sont construits par le code à partir de dates et vérifiés par
expression régulière : aucune valeur extérieure n'entre dans le SQL.
Aucune fonction ne committe : l'appelant prend le verrou de maintenance."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.metric_point import DEFAULT_PARTITION
from app.services.metrics.aggregate import month_start

RETENTION_MONTHS = 25
_NAME = re.compile(r"^metric_points_p\d{4}_\d{2}$")
_BOUNDS = re.compile(r"FOR VALUES FROM \('(\d{4}-\d{2}-\d{2})'\) TO \('(\d{4}-\d{2}-\d{2})'\)")


@dataclass(frozen=True, slots=True)
class Partition:
    name: str
    start: date | None
    end: date | None


@dataclass(frozen=True, slots=True)
class PurgeResult:
    dropped: tuple[str, ...]
    deleted_default_rows: int


def add_months(month: date, count: int) -> date:
    index = month.year * 12 + (month.month - 1) + count
    return date(index // 12, index % 12 + 1, 1)


def partition_name(month: date) -> str:
    return f"metric_points_p{month:%Y_%m}"


def _checked(name: str) -> str:
    if not _NAME.match(name):
        raise ValueError(f"nom de partition inattendu : {name}")
    return name


async def list_partitions(session: AsyncSession) -> list[Partition]:
    rows = await session.execute(
        text(
            "SELECT c.relname, pg_get_expr(c.relpartbound, c.oid) "
            "FROM pg_inherits i "
            "JOIN pg_class c ON c.oid = i.inhrelid "
            "JOIN pg_class p ON p.oid = i.inhparent "
            "WHERE p.relname = 'metric_points' ORDER BY c.relname"
        )
    )
    partitions: list[Partition] = []
    for name, bound in rows.all():
        match = _BOUNDS.search(bound or "")
        if match is None:
            partitions.append(Partition(name=name, start=None, end=None))
        else:
            partitions.append(
                Partition(
                    name=name,
                    start=date.fromisoformat(match.group(1)),
                    end=date.fromisoformat(match.group(2)),
                )
            )
    return partitions


async def _create_partition(session: AsyncSession, start: date) -> str:
    end = add_months(start, 1)
    name = _checked(partition_name(start))
    async with session.begin_nested():
        await session.execute(text(f"LOCK TABLE {DEFAULT_PARTITION} IN ACCESS EXCLUSIVE MODE"))
        await session.execute(
            text(
                f"CREATE TABLE {name} (LIKE metric_points "
                "INCLUDING DEFAULTS INCLUDING CONSTRAINTS)"
            )
        )
        await session.execute(
            text(
                f"WITH moved AS (DELETE FROM {DEFAULT_PARTITION} "
                "WHERE day >= :start AND day < :end RETURNING *) "
                f"INSERT INTO {name} SELECT * FROM moved"
            ),
            {"start": start, "end": end},
        )
        await session.execute(
            text(
                f"ALTER TABLE metric_points ATTACH PARTITION {name} "
                f"FOR VALUES FROM ('{start.isoformat()}') TO ('{end.isoformat()}')"
            )
        )
    return name


async def ensure_partitions(
    session: AsyncSession, *, today: date, months_back: int = 4, months_ahead: int = 3
) -> list[str]:
    existing = {p.start for p in await list_partitions(session) if p.start is not None}
    current = month_start(today)
    created: list[str] = []
    for offset in range(-months_back, months_ahead + 1):
        start = add_months(current, offset)
        if start in existing:
            continue
        created.append(await _create_partition(session, start))
    return created


async def purge_expired(
    session: AsyncSession, *, today: date, retention_months: int = RETENTION_MONTHS
) -> PurgeResult:
    cutoff = add_months(month_start(today), -retention_months)
    dropped: list[str] = []
    for partition in await list_partitions(session):
        if partition.end is None or partition.end > cutoff:
            continue
        name = _checked(partition.name)
        await session.execute(text(f"ALTER TABLE metric_points DETACH PARTITION {name}"))
        await session.execute(text(f"DROP TABLE {name}"))
        dropped.append(name)
    result = await session.execute(
        text(f"DELETE FROM {DEFAULT_PARTITION} WHERE day < :cutoff"), {"cutoff": cutoff}
    )
    return PurgeResult(dropped=tuple(dropped), deleted_default_rows=result.rowcount or 0)
