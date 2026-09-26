"""Doubles et utilitaires des tests du lot B (tâches planifiées) : aucun réseau."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.website import Website
from app.services.jobs.handlers import JobServices
from app.services.jobs.queue import EnqueueError, TaskMessage
from app.services.jobs.runner import JobLimits
from app.services.measurement.google_reader import GoogleReadError
from app.services.metrics.types import SOURCE_SPECS, DayRange, Observation, SourceError
from tests.conftest import owner_workspace_id

TODAY = date(2026, 9, 26)
NOW = datetime(2026, 9, 26, 6, 7, tzinfo=UTC)

LIMITS = JobLimits(lease=timedelta(minutes=15), max_attempts=3, workspace_concurrency=2)


async def make_site(db_session: AsyncSession, make_user, domain: str) -> Website:
    user = await make_user(sub=f"jobs-{domain}")
    workspace_id = await owner_workspace_id(db_session, user)
    site = Website(workspace_id=workspace_id, domain=domain, display_name=domain)
    db_session.add(site)
    await db_session.flush()
    return site


class RecordingQueue:
    """File factice : enregistre les dépôts ; `failing_kinds` simule une panne de dépôt."""

    def __init__(self, *, failing_kinds: frozenset[str] = frozenset()) -> None:
        self.messages: list[TaskMessage] = []
        self._failing = failing_kinds

    async def enqueue(self, message: TaskMessage) -> None:
        if message.spec.kind in self._failing:
            raise EnqueueError("network")
        self.messages.append(message)


class FakeSource:
    """Source factice : renvoie les observations comprises dans la fenêtre demandée.

    - `error` : levée à chaque appel, ou seulement au n-ième (1-based) si `error_on_call`
      est donné (mutable : un test peut « réparer » la source entre deux exécutions) ;
    - `session` : si fournie, vérifie qu'AUCUNE transaction n'est ouverte pendant
      l'appel réseau simulé."""

    def __init__(
        self,
        name: str,
        observations: Sequence[Observation] = (),
        error: SourceError | None = None,
        *,
        error_on_call: int | None = None,
        session: AsyncSession | None = None,
    ) -> None:
        self.spec = SOURCE_SPECS[name]
        self._observations = list(observations)
        self.error = error
        self.error_on_call = error_on_call
        self._session = session
        self.calls: list[DayRange] = []

    async def collect(self, website, day_range: DayRange) -> list[Observation]:
        if self._session is not None:
            assert not self._session.in_transaction(), "transaction ouverte pendant le réseau"
        self.calls.append(day_range)
        if self.error is not None and self.error_on_call in (None, len(self.calls)):
            raise self.error
        return [obs for obs in self._observations if day_range.contains(obs.day)]


class UnlinkedReader:
    """Lecteur Google d'un site sans GA4 ni Search Console reliés (aucun réseau)."""

    gsc_state = "not_linked"

    async def event_stats(self):
        raise GoogleReadError("ga4_not_connected")

    key_events = ads_links_count = measurement_id = event_stats

    async def sitemaps_count(self):
        raise GoogleReadError("gsc_not_connected")


async def offline_fetcher(url: str, *, allow_insecure: bool = False):
    _ = (url, allow_insecure)
    return None  # site injoignable : aucun DNS, aucun réseau


async def unlinked_reader_factory(session, website) -> UnlinkedReader:
    _ = (session, website)
    return UnlinkedReader()


def fake_services(sources: dict[str, FakeSource], calls: list[str] | None = None) -> JobServices:
    async def factory(session, website, name: str):
        if calls is not None:
            calls.append(name)
        return sources[name]

    return JobServices.from_clock(
        source_factory=factory,
        page_fetcher=offline_fetcher,
        reader_factory=unlinked_reader_factory,
        clock=lambda: NOW,
    )
