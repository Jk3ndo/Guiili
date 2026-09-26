"""Gestionnaires des types de tâches.

Chaque gestionnaire reçoit la session (aucune transaction ouverte) et le `JobRun`
réclamé, lève `SourceError` pour un échec typé et ne committe que ses étapes
intermédiaires : `execute_run` enregistre le résultat final et le planning."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from functools import partial
from uuid import UUID

from sqlalchemy import and_, delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.job_run import JobRun
from app.models.website import Website
from app.services.gtm_headless import GtmHeadlessResult
from app.services.jobs.kinds import BACKFILL_SOURCES, COLLECT_KIND_BY_SOURCE
from app.services.jobs.runner import Handler, HandlerOutcome, lock_key
from app.services.measurement.fetch import PageFetcher
from app.services.measurement.service import ReaderFactory, refresh_plan
from app.services.metrics.partitions import ensure_partitions, purge_expired
from app.services.metrics.sources.factory import SourceFactory
from app.services.metrics.store import store_observations
from app.services.metrics.types import MetricSource, SourceError, utc_now, utc_today

logger = logging.getLogger(__name__)

BREAKER_WINDOW = timedelta(minutes=30)
BREAKER_THRESHOLD = 3
JOB_RUNS_RETENTION = timedelta(days=90)

# Une sonde complète produit les deux mesures ; l'absence de l'une (TLS illisible, page
# muette) est un résultat partiel, à signaler sans en faire un échec.
_PROBE_METRICS = frozenset({"tls_days_remaining", "page_up"})
PROBE_PARTIAL = "probe_partial"


@dataclass(frozen=True, slots=True)
class JobServices:
    source_factory: SourceFactory
    page_fetcher: PageFetcher
    reader_factory: ReaderFactory
    today: Callable[[], date] = utc_today
    now: Callable[[], datetime] = utc_now


async def _active_website(session: AsyncSession, run: JobRun) -> Website:
    website = await session.get(Website, run.website_id) if run.website_id else None
    if website is None or website.archived_at is not None:
        raise SourceError("website_inactive", recoverable=False, not_applicable=True)
    return website


async def quota_breaker_open(
    session: AsyncSession, *, workspace_id: UUID, source: str, now: datetime
) -> bool:
    """Disjoncteur (spec §6 mesure 8) : trop d'échecs `quota` récents pour ce workspace
    et cette source Google ⇒ on n'appelle plus Google pendant `BREAKER_WINDOW`."""
    kind = COLLECT_KIND_BY_SOURCE[source]
    count = await session.scalar(
        select(func.count())
        .select_from(JobRun)
        .where(
            JobRun.workspace_id == workspace_id,
            JobRun.error_code == "quota",
            JobRun.finished_at >= now - BREAKER_WINDOW,
            or_(
                JobRun.kind == kind,
                and_(JobRun.kind == "backfill", JobRun.params["source"].astext == source),
            ),
        )
    )
    return (count or 0) >= BREAKER_THRESHOLD


async def _open_source(
    services: JobServices, session: AsyncSession, website: Website, name: str, run: JobRun
) -> MetricSource:
    if (
        name in BACKFILL_SOURCES
        and run.workspace_id is not None
        and await quota_breaker_open(
            session, workspace_id=run.workspace_id, source=name, now=services.now()
        )
    ):
        raise SourceError("circuit_open", recoverable=True)
    try:
        source = await services.source_factory(session, website, name)
    except SourceError:
        # Une connexion passée à `needs_reauth` avant l'échec doit survivre au `rollback`
        # de l'exécuteur : on enregistre ces effets avant de propager l'erreur typée.
        await session.commit()
        raise
    # Jetons résolus (et éventuel passage à `needs_reauth`) enregistrés : plus aucune
    # transaction n'est ouverte pendant la collecte réseau.
    await session.commit()
    return source


async def collect(
    services: JobServices, name: str, session: AsyncSession, run: JobRun
) -> HandlerOutcome:
    website = await _active_website(session, run)
    source = await _open_source(services, session, website, name, run)
    observations = await source.collect(website, source.spec.regular_window(services.today()))
    result = await store_observations(
        session,
        website_id=website.id,
        source=name,
        observations=observations,
        run_id=run.id,
        now=services.now(),
    )
    if name == "probe" and _PROBE_METRICS - {obs.metric for obs in observations}:
        logger.warning(
            "sonde partielle : une des deux mesures manque",
            extra={"event": "probe_partial", "website_id": str(website.id)},
        )
        return HandlerOutcome(observations=result.written, note=PROBE_PARTIAL)
    return HandlerOutcome(observations=result.written)


async def backfill(services: JobServices, session: AsyncSession, run: JobRun) -> HandlerOutcome:
    name = str(run.params.get("source", ""))
    if name not in BACKFILL_SOURCES:
        raise SourceError("bad_params", recoverable=False)
    website = await _active_website(session, run)
    source = await _open_source(services, session, website, name, run)
    window = source.spec.backfill_window(services.today())
    if window is None:
        raise SourceError("bad_params", recoverable=False)
    written = 0
    for chunk in window.chunks(source.spec.max_days_per_call):
        observations = await source.collect(website, chunk)
        result = await store_observations(
            session,
            website_id=website.id,
            source=name,
            observations=observations,
            run_id=run.id,
            now=services.now(),
        )
        # Progression conservée tranche par tranche : une reprise réécrit à l'identique.
        await session.commit()
        written += result.written
    return HandlerOutcome(observations=written)


async def _no_browser(url: str) -> GtmHeadlessResult:
    raise RuntimeError(f"le navigateur n'est jamais lancé par une tâche planifiée ({url})")


async def measurement_check(
    services: JobServices, session: AsyncSession, run: JobRun
) -> HandlerOutcome:
    """Vérification légère planifiée du plan de mesure (spec §9 point 8) : même service
    que le bouton « Vérifier maintenant », sans navigateur, sous le verrou du site."""
    website = await _active_website(session, run)
    reader = await services.reader_factory(session, website)
    # Une connexion Google passée à `needs_reauth` par la construction du lecteur est
    # enregistrée avant le rafraîchissement (qui tient ensuite le verrou du site).
    await session.commit()
    await refresh_plan(
        session,
        website,
        fetcher=services.page_fetcher,
        reader=reader,
        verifier=_no_browser,
        run_headless=False,
        now=services.now(),
    )
    return HandlerOutcome()


async def purge_old_job_runs(
    session: AsyncSession, *, now: datetime, keep: timedelta = JOB_RUNS_RETENTION
) -> int:
    result = await session.execute(
        delete(JobRun).where(JobRun.finished_at.is_not(None), JobRun.finished_at < now - keep)
    )
    return result.rowcount or 0


async def partition_maintenance(
    services: JobServices, session: AsyncSession, run: JobRun
) -> HandlerOutcome:
    """Création des mois à venir puis purge, en DEUX transactions (jamais ensemble : le
    1er du mois, la création du mois M+3 et la purge du mois M-26 pourraient s'interbloquer
    avec une collecte). Chaque transaction reprend le verrou de maintenance."""
    _ = run
    await lock_key(session, "partition_maintenance")
    created = await ensure_partitions(session, today=services.today())
    await session.commit()

    await lock_key(session, "partition_maintenance")
    purged = await purge_expired(session, today=services.today())
    deleted_runs = await purge_old_job_runs(session, now=services.now())
    await session.commit()

    logger.info(
        "maintenance du stockage des mesures",
        extra={
            "event": "partition_maintenance",
            "created_partitions": created,
            "dropped_partitions": list(purged.dropped),
            "deleted_default_rows": purged.deleted_default_rows,
            "deleted_job_runs": deleted_runs,
        },
    )
    if purged.unexpected:
        # Le reste de la purge a eu lieu ; on ne touche jamais à ces partitions, mais
        # l'opérateur doit le savoir : la tâche échoue (sans nouvelle tentative utile).
        logger.error(
            "partitions de métriques inattendues, laissées en place",
            extra={"event": "partition_unexpected", "partitions": list(purged.unexpected)},
        )
        raise SourceError("unexpected_partitions", recoverable=False)
    return HandlerOutcome()


def build_handlers(services: JobServices) -> dict[str, Handler]:
    handlers: dict[str, Handler] = {
        "backfill": partial(backfill, services),
        "measurement_check": partial(measurement_check, services),
        "partition_maintenance": partial(partition_maintenance, services),
    }
    for source, kind in COLLECT_KIND_BY_SOURCE.items():
        handlers[kind] = partial(collect, services, source)
    return handlers
