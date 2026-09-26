"""Construit la `MetricSource` d'un site pour une source donnée. Les sources Google
lisent les jetons des liaisons du site (base + rafraîchissement OAuth) : l'appelant
committe ensuite, AVANT de lancer la collecte réseau.

`clock` (horloge injectable, la MÊME que celle de `JobServices.from_clock`) fournit la
date des sources qui datent leurs observations elles-mêmes (Core Web Vitals, sondes).
La sonde TLS lit aussi l'heure : c'est à l'appelant de fournir un `tls_checker` déjà lié
à la même horloge."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import date, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.website import Website
from app.services.audit_engine import TlsChecker
from app.services.measurement.fetch import PageFetcher
from app.services.metrics.sources.credentials import resolve_google_credentials
from app.services.metrics.sources.cwv import CwvSource
from app.services.metrics.sources.ga4 import Ga4Source
from app.services.metrics.sources.gsc import GscSource
from app.services.metrics.sources.probes import ProbeSource
from app.services.metrics.types import MetricSource, SourceError, utc_now

SourceFactory = Callable[[AsyncSession, Website, str], Awaitable[MetricSource]]


def default_source_factory(
    *,
    pagespeed_api_key: str | None,
    oauth: Any,
    cipher: Any,
    tls_checker: TlsChecker,
    page_fetcher: PageFetcher,
    clock: Callable[[], datetime] = utc_now,
) -> SourceFactory:
    def today() -> date:
        return clock().date()

    async def build(session: AsyncSession, website: Website, name: str) -> MetricSource:
        if name in ("ga4", "gsc"):
            credentials = await resolve_google_credentials(
                session, website, oauth=oauth, cipher=cipher
            )
            # `token_problem` distingue un jeton à reconnecter (définitif) d'un
            # rafraîchissement en échec passager (récupérable).
            if name == "ga4":
                return Ga4Source(
                    property_id=credentials.ga4_property,
                    token=credentials.ga4_token,
                    token_problem=credentials.ga4_problem,
                )
            return GscSource(
                site_url=credentials.gsc_site,
                token=credentials.gsc_token,
                token_problem=credentials.gsc_problem,
            )
        if name == "cwv":
            return CwvSource(api_key=pagespeed_api_key, today=today)
        if name == "probe":
            return ProbeSource(tls_checker=tls_checker, page_fetcher=page_fetcher, today=today)
        raise SourceError("unknown_source", recoverable=False)

    return build
