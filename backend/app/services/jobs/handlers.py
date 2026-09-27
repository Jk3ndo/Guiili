"""Gestionnaires des types de tâches.

Chaque gestionnaire reçoit la session (aucune transaction ouverte) et le `JobRun`
réclamé, lève `SourceError` pour un échec typé et ne committe que ses étapes
intermédiaires : `execute_run` enregistre le résultat final et le planning."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from functools import partial
from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.models.job_run import JobRun
from app.models.source_quota_event import SourceQuotaEvent
from app.models.website import Website
from app.security.token_crypto import load_token_cipher
from app.services.google_oauth import get_google_oauth_client
from app.services.gtm_headless import GtmHeadlessResult
from app.services.jobs.kinds import BACKFILL_SOURCES, COLLECT_KIND_BY_SOURCE
from app.services.jobs.runner import Handler, HandlerOutcome, lock_key
from app.services.measurement.fetch import PageFetcher, fetch_page_safe
from app.services.measurement.google_access import build_reader
from app.services.measurement.service import ReaderFactory, refresh_plan
from app.services.metrics.partitions import ensure_partitions, purge_expired
from app.services.metrics.sources.factory import SourceFactory, default_source_factory
from app.services.metrics.store import store_observations
from app.services.metrics.types import (
    DayRange,
    MetricSource,
    Observation,
    SourceError,
    utc_now,
)
from app.services.tls_check import check_certificate

logger = logging.getLogger(__name__)

BREAKER_WINDOW = timedelta(minutes=30)
BREAKER_THRESHOLD = 3
JOB_RUNS_RETENTION = timedelta(days=90)
# Les événements de quota ne servent qu'à la fenêtre du disjoncteur : 2 jours de marge.
QUOTA_EVENTS_RETENTION = timedelta(days=2)
# Borne de la vérification du plan de mesure : `refresh_plan` garde une transaction (et
# le verrou du site) ouverte pendant ses appels réseau (pire cas ~100 s).
MEASUREMENT_CHECK_TIMEOUT_SECONDS = 120

# Une sonde complète produit les deux mesures ; l'absence de l'une (TLS illisible, page
# muette) est un résultat partiel, à signaler sans en faire un échec.
_PROBE_METRICS = frozenset({"tls_days_remaining", "page_up"})
PROBE_PARTIAL = "probe_partial"


def _default_today() -> date:
    return utc_now().date()


@dataclass(frozen=True, slots=True)
class JobServices:
    source_factory: SourceFactory
    page_fetcher: PageFetcher
    reader_factory: ReaderFactory
    today: Callable[[], date] = field(default=_default_today)
    now: Callable[[], datetime] = field(default=utc_now)

    @classmethod
    def from_clock(
        cls,
        *,
        source_factory: SourceFactory,
        page_fetcher: PageFetcher,
        reader_factory: ReaderFactory,
        clock: Callable[[], datetime] = utc_now,
    ) -> JobServices:
        """Services dont la date et l'heure dérivent de la MÊME horloge (à donner aussi à
        `default_source_factory(clock=...)`) : jamais deux horloges qui divergent."""

        def today() -> date:
            return clock().date()

        return cls(
            source_factory=source_factory,
            page_fetcher=page_fetcher,
            reader_factory=reader_factory,
            today=today,
            now=clock,
        )


async def _active_website(session: AsyncSession, run: JobRun) -> Website:
    website = await session.get(Website, run.website_id) if run.website_id else None
    if website is None or website.archived_at is not None:
        raise SourceError("website_inactive", recoverable=False, not_applicable=True)
    return website


async def quota_breaker_open(
    session: AsyncSession, *, workspace_id: UUID, source: str, now: datetime
) -> bool:
    """Disjoncteur (spec §6 mesure 8) : `BREAKER_THRESHOLD` échecs `quota` en
    `BREAKER_WINDOW` pour ce workspace et cette source Google ⇒ on n'appelle plus Google.
    Le décompte lit `source_quota_events` (ajout seul) et non `job_runs` : une nouvelle
    tentative réécrit la ligne de sa tâche, ce qui ferait retomber le compteur."""
    count = await session.scalar(
        select(func.count())
        .select_from(SourceQuotaEvent)
        .where(
            SourceQuotaEvent.workspace_id == workspace_id,
            SourceQuotaEvent.source == source,
            SourceQuotaEvent.at >= now - BREAKER_WINDOW,
        )
    )
    return (count or 0) >= BREAKER_THRESHOLD


async def _record_quota_event(
    services: JobServices, session: AsyncSession, run: JobRun, name: str
) -> None:
    """Un échec `quota` = UN événement, committé avant de propager l'erreur (l'exécuteur
    fait `rollback`). L'échec `circuit_open` n'en enregistre aucun : il n'appelle pas
    Google."""
    if run.workspace_id is None:
        return
    session.add(SourceQuotaEvent(workspace_id=run.workspace_id, source=name, at=services.now()))
    await session.commit()


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


async def _fetch(
    services: JobServices,
    session: AsyncSession,
    run: JobRun,
    source: MetricSource,
    name: str,
    website: Website,
    window: DayRange,
) -> list[Observation]:
    try:
        return await source.collect(website, window)
    except SourceError as exc:
        if exc.reason == "quota":
            await _record_quota_event(services, session, run, name)
        raise


async def collect(
    services: JobServices, name: str, session: AsyncSession, run: JobRun
) -> HandlerOutcome:
    website = await _active_website(session, run)
    source = await _open_source(services, session, website, name, run)
    window = source.spec.regular_window(services.today())
    observations = await _fetch(services, session, run, source, name, website, window)
    if name in ("probe", "cwv") and not observations:
        # Une sonde ou une collecte CWV sans aucune mesure n'est pas une réussite
        # silencieuse : mieux vaut échouer (nouvel essai) qu'un « à jour » mensonger.
        raise SourceError("no_observation", recoverable=True)
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
        observations = await _fetch(services, session, run, source, name, website, chunk)
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
    # `TimeoutError` : reclassée par l'exécuteur en `internal_error` récupérable, avec
    # `rollback` (libère la transaction et le verrou du site).
    async with asyncio.timeout(MEASUREMENT_CHECK_TIMEOUT_SECONDS):
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


async def purge_old_quota_events(
    session: AsyncSession, *, now: datetime, keep: timedelta = QUOTA_EVENTS_RETENTION
) -> int:
    result = await session.execute(delete(SourceQuotaEvent).where(SourceQuotaEvent.at < now - keep))
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
    deleted_quota_events = await purge_old_quota_events(session, now=services.now())
    await session.commit()

    logger.info(
        "maintenance du stockage des mesures",
        extra={
            "event": "partition_maintenance",
            "created_partitions": created,
            "dropped_partitions": list(purged.dropped),
            "deleted_default_rows": purged.deleted_default_rows,
            "deleted_job_runs": deleted_runs,
            "deleted_quota_events": deleted_quota_events,
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


def default_job_services(settings: Settings) -> JobServices:
    """Services réels (réseau) : utilisés par le worker et l'outil local, jamais en test.

    Une seule horloge (`utc_now`) alimente les dates des sources, la sonde TLS et
    `JobServices` : jamais deux horloges qui divergent."""
    oauth = get_google_oauth_client(settings)
    cipher = load_token_cipher(settings)
    clock = utc_now

    async def reader_factory(session: AsyncSession, website: Website):
        return await build_reader(session, website, oauth=oauth, cipher=cipher)

    async def tls_checker(domain: str):
        return await check_certificate(domain, now=clock())

    return JobServices.from_clock(
        source_factory=default_source_factory(
            pagespeed_api_key=settings.pagespeed_api_key.get_secret_value() or None,
            oauth=oauth,
            cipher=cipher,
            tls_checker=tls_checker,
            page_fetcher=fetch_page_safe,
            clock=clock,
        ),
        page_fetcher=fetch_page_safe,
        reader_factory=reader_factory,
        clock=clock,
    )
