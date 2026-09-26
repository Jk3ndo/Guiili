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

# 404/410 : la page d'accueil n'existe plus, c'est une vraie panne, au même titre qu'un 5xx.
_DOWN_STATUSES = frozenset({404, 410})


def _page_up(status: int) -> float | None:
    """1 si la page répond, 0 si elle est en panne, `None` si on ne peut pas conclure
    (401/403/429 et autres 4xx : un pare-feu, un anti-bot ou une limite de débit répond,
    aucune observation plutôt qu'une fausse panne)."""
    if status >= 500 or status in _DOWN_STATUSES:
        return 0.0
    if status < 400:
        return 1.0
    return None


def _kind(exc: Exception) -> str:
    # Le type seul : le message d'une exception réseau peut citer une URL.
    return type(exc).__name__


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
        # Une exception inattendue d'une sonde (autre que httpx : URL invalide, socket...)
        # ne doit ni perdre l'observation de l'autre sonde ni fuiter son message.
        try:
            tls = await self._tls_checker(website.domain)
        except Exception as exc:
            logger.warning(
                "sonde TLS en erreur", extra={"website_id": str(website.id), "error": _kind(exc)}
            )
        else:
            if tls.status != "unreachable" and tls.days_remaining is not None:
                observations.append(
                    Observation("tls_days_remaining", day, float(tls.days_remaining))
                )
            else:
                logger.info("sonde TLS sans résultat", extra={"website_id": str(website.id)})
        try:
            page = await self._page_fetcher(
                f"https://{website.domain}", allow_insecure=bool(website.allow_insecure_probe)
            )
        except Exception as exc:
            logger.warning(
                "sonde de disponibilité en erreur",
                extra={"website_id": str(website.id), "error": _kind(exc)},
            )
            page = None
        else:
            if page is None:
                logger.info("page d'accueil injoignable", extra={"website_id": str(website.id)})
        if page is not None:
            page_up = _page_up(page.status)
            if page_up is None:
                # 401/403/429 : un pare-feu ou un anti-bot répond, la page n'est pas en panne.
                logger.info(
                    "disponibilité non concluante", extra={"website_id": str(website.id)}
                )
            else:
                observations.append(Observation("page_up", day, page_up))
        if not observations:
            raise SourceError("unreachable", recoverable=True)
        return observations
