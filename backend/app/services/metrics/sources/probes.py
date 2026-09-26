"""Sondes légères : jours restants du certificat HTTPS et disponibilité de la page
d'accueil. Un certificat expiré (jours négatifs) ou une réponse 5xx sont de vraies
observations ; un site qui ne répond pas du tout n'en produit aucune (on ne sait pas si
la panne vient de lui ou du réseau)."""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import date

from app.models.website import Website
from app.services.audit_engine import TlsChecker
from app.services.measurement.fetch import PageFetcher
from app.services.metrics.types import (
    SOURCE_SPECS,
    DayRange,
    Observation,
    SourceError,
    SourceSpec,
    utc_today,
)

logger = logging.getLogger(__name__)


class ProbeSource:
    spec: SourceSpec = SOURCE_SPECS["probe"]

    def __init__(
        self,
        *,
        tls_checker: TlsChecker,
        page_fetcher: PageFetcher,
        today: Callable[[], date] = utc_today,
    ) -> None:
        self._tls_checker = tls_checker
        self._page_fetcher = page_fetcher
        self._today = today

    async def collect(self, website: Website, day_range: DayRange) -> list[Observation]:
        day = self._today()
        if not day_range.contains(day):
            return []
        observations: list[Observation] = []
        tls = await self._tls_checker(website.domain)
        if tls.status != "unreachable" and tls.days_remaining is not None:
            observations.append(Observation("tls_days_remaining", day, float(tls.days_remaining)))
        else:
            logger.info("sonde TLS sans résultat", extra={"website_id": str(website.id)})
        page = await self._page_fetcher(
            f"https://{website.domain}", allow_insecure=bool(website.allow_insecure_probe)
        )
        if page is not None:
            observations.append(Observation("page_up", day, 1.0 if page.status < 400 else 0.0))
        else:
            logger.info("page d'accueil injoignable", extra={"website_id": str(website.id)})
        if not observations:
            raise SourceError("unreachable", recoverable=True)
        return observations
