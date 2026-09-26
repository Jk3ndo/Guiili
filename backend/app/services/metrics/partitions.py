"""Partitions mensuelles de `metric_points`.

- `ensure_partitions` crée d'avance les mois manquants autour d'aujourd'hui. Si des
  lignes de ce mois attendent dans la partition par défaut, PostgreSQL refuse de créer
  la partition (« updated partition constraint for default partition would be violated
  ») : on crée donc une table vide de même forme, on y déplace ces lignes, puis on
  l'attache. Chaque mois est créé dans un point de sauvegarde : si une étape échoue, la
  table intermédiaire est annulée avec le reste (jamais de table orpheline qui ferait
  échouer une migration ultérieure).
- `purge_expired` détache et supprime les partitions entièrement plus vieilles que la
  rétention (25 mois, comparaison annuelle), et purge la partition par défaut au-delà.
  Seul ce qui est prouvé hors rétention est supprimé : une partition n'est retirée que
  si sa borne de fin (exclue) est antérieure ou égale à la limite. Une partition dont
  le nom ou la borne n'est pas celui que ce module crée n'est jamais touchée : son nom
  est renvoyé dans `PurgeResult.unexpected` (l'appelant le journalise en ERROR et
  marque l'exécution en échec) et le reste de la purge continue.

Verrous PostgreSQL réellement pris (tous gardés jusqu'au commit de l'appelant ; libérer
un point de sauvegarde ne rend pas les verrous) :
- `_create_partition` : `ACCESS EXCLUSIVE` sur la partition par défaut (pour que
  personne n'y écrive une ligne du mois pendant le déplacement), puis `SHARE UPDATE
  EXCLUSIVE` sur le parent `metric_points` lors de l'ATTACH.
- `purge_expired` : `DETACH PARTITION` non concurrent = `ACCESS EXCLUSIVE` sur le
  parent `metric_points` : toute lecture et écriture de métriques attend.
Conséquences :
- Un INSERT concurrent d'une ligne du mois en cours de création peut échouer (« violates
  partition constraint » : PostgreSQL revérifie la contrainte de la partition par
  défaut) au lieu d'attendre. Cet échec est récupérable : la collecte retente.
- Un DETACH en attente d'un verrou bloque aussi toutes les requêtes suivantes sur la
  table : `SET LOCAL lock_timeout = '5s'` en tête de chaque fonction fait échouer vite
  (le job échoue puis réessaie) plutôt que de figer les métriques.
- Contrat pour l'appelant : `ensure_partitions` et `purge_expired` s'exécutent dans DEUX
  transactions séparées, avec un commit entre les deux, et sous le verrou de maintenance.
  Ensemble dans une seule transaction, le 1er du mois (mois M+3 créé, mois M-26 purgé),
  ils pourraient s'interbloquer avec une collecte en cours ; séparés, un échec de purge
  n'annule pas la création des mois à venir.
Aucune fonction ne committe.
Les noms de tables sont construits par le code à partir de dates et vérifiés par
expression régulière : aucune valeur extérieure n'entre dans le SQL."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import Literal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.metric_point import DEFAULT_PARTITION, MetricPoint
from app.services.metrics.aggregate import month_start

RETENTION_MONTHS = 25
LOCK_TIMEOUT = "5s"
_NAME = re.compile(r"^metric_points_p\d{4}_\d{2}$")
_BOUNDS = re.compile(r"FOR VALUES FROM \('(\d{4}-\d{2}-\d{2})'\) TO \('(\d{4}-\d{2}-\d{2})'\)")
# Noms de colonnes tirés du modèle (jamais d'une entrée extérieure).
_COLUMNS = ", ".join(column.name for column in MetricPoint.__table__.columns)

PartitionKind = Literal["default", "range", "unknown"]


@dataclass(frozen=True, slots=True)
class Partition:
    """`kind` : "default" (partition attrape-tout, `start` et `end` valent None),
    "range" (bornes mensuelles connues) ou "unknown" (borne non reconnue : jamais
    traitée comme la partition par défaut, jamais purgée)."""

    name: str
    start: date | None
    end: date | None
    kind: PartitionKind = "range"


@dataclass(frozen=True, slots=True)
class PurgeResult:
    dropped: tuple[str, ...]
    deleted_default_rows: int
    unexpected: tuple[str, ...] = ()


def add_months(month: date, count: int) -> date:
    index = month.year * 12 + (month.month - 1) + count
    return date(index // 12, index % 12 + 1, 1)


def partition_name(month: date) -> str:
    return f"metric_points_p{month:%Y_%m}"


def _checked(name: str) -> str:
    if not _NAME.match(name):
        raise ValueError(f"nom de partition inattendu : {name}")
    return name


async def _set_lock_timeout(session: AsyncSession) -> None:
    await session.execute(text(f"SET LOCAL lock_timeout = '{LOCK_TIMEOUT}'"))


async def list_partitions(session: AsyncSession) -> list[Partition]:
    rows = await session.execute(
        text(
            "SELECT c.relname, pg_get_expr(c.relpartbound, c.oid) "
            "FROM pg_inherits i "
            "JOIN pg_class c ON c.oid = i.inhrelid "
            "WHERE i.inhparent = 'metric_points'::regclass ORDER BY c.relname"
        )
    )
    partitions: list[Partition] = []
    for name, bound in rows.all():
        expression = (bound or "").strip()
        match = _BOUNDS.fullmatch(expression)
        if expression == "DEFAULT":
            partitions.append(Partition(name=name, start=None, end=None, kind="default"))
        elif match is None:
            partitions.append(Partition(name=name, start=None, end=None, kind="unknown"))
        else:
            partitions.append(
                Partition(
                    name=name,
                    start=date.fromisoformat(match.group(1)),
                    end=date.fromisoformat(match.group(2)),
                    kind="range",
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
                f"WHERE day >= :start AND day < :end RETURNING {_COLUMNS}) "
                f"INSERT INTO {name} ({_COLUMNS}) SELECT {_COLUMNS} FROM moved"
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
    if months_back < 0 or months_ahead < 0:
        raise ValueError("months_back et months_ahead doivent être positifs ou nuls")
    await _set_lock_timeout(session)
    existing = {p.start for p in await list_partitions(session) if p.kind == "range"}
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
    if retention_months < 1:
        # 0 ou moins supprimerait la partition du mois courant.
        raise ValueError("retention_months doit valoir au moins 1")
    await _set_lock_timeout(session)
    cutoff = add_months(month_start(today), -retention_months)
    dropped: list[str] = []
    unexpected: list[str] = []
    for partition in await list_partitions(session):
        if partition.kind == "default":
            continue
        if partition.kind == "unknown":
            unexpected.append(partition.name)
            continue
        if partition.end is None or partition.end > cutoff:
            continue
        if not _NAME.match(partition.name):
            unexpected.append(partition.name)
            continue
        name = _checked(partition.name)
        await session.execute(text(f"ALTER TABLE metric_points DETACH PARTITION {name}"))
        await session.execute(text(f"DROP TABLE {name}"))
        dropped.append(name)
    result = await session.execute(
        text(f"DELETE FROM {DEFAULT_PARTITION} WHERE day < :cutoff"), {"cutoff": cutoff}
    )
    return PurgeResult(
        dropped=tuple(dropped),
        deleted_default_rows=result.rowcount or 0,
        unexpected=tuple(unexpected),
    )
