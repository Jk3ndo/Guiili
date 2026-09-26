"""Appel du service worker par l'API : vérification headless (l'image de l'API n'a plus
Chromium). Jeton d'identité du compte de service de l'API (serveur de métadonnées),
vérifié par le worker. Ne lève jamais : toute panne devient un résultat en échec,
exactement comme un échec local de `verify_gtm`."""

from __future__ import annotations

import logging
from datetime import UTC, datetime

import httpx

from app.services.gcp_metadata import IdentityTokenProvider, MetadataError
from app.services.gtm_headless import (
    HEADLESS_FAILED,
    GtmHeadlessResult,
    headless_result_from_dict,
)

logger = logging.getLogger(__name__)


def _failed() -> GtmHeadlessResult:
    return GtmHeadlessResult(
        gtm_js_loaded=False,
        containers_initialised=(),
        datalayer_present=False,
        gtm_events=(),
        requests_before_consent=False,
        csp_console_errors=(),
        findings=(),
        checked_at=datetime.now(UTC),
        error=HEADLESS_FAILED,
    )


class RemoteHeadlessVerifier:
    def __init__(
        self,
        *,
        base_url: str,
        audience: str,
        tokens: IdentityTokenProvider,
        client: httpx.AsyncClient | None = None,
        timeout: float = 150.0,
    ) -> None:
        self._url = f"{base_url.rstrip('/')}/internal/headless/verify"
        self._audience = audience
        self._tokens = tokens
        self._client = client
        self._timeout = httpx.Timeout(timeout)

    async def __call__(self, url: str) -> GtmHeadlessResult:
        try:
            token = await self._tokens.identity_token(self._audience)
        except MetadataError:
            logger.warning(
                "jeton d'identité indisponible pour le worker",
                extra={"event": "headless_delegation"},
            )
            return _failed()
        owns = self._client is None
        http = self._client or httpx.AsyncClient(timeout=self._timeout)
        try:
            response = await http.post(
                self._url, json={"url": url}, headers={"Authorization": f"Bearer {token}"}
            )
        except httpx.HTTPError as exc:
            logger.warning(
                "worker injoignable pour la vérification headless",
                extra={"event": "headless_delegation", "error": type(exc).__name__},
            )
            return _failed()
        finally:
            if owns:
                await http.aclose()
        if response.status_code != 200:
            logger.warning(
                "le worker a refusé la vérification headless",
                extra={"event": "headless_delegation", "status": response.status_code},
            )
            return _failed()
        try:
            return headless_result_from_dict(response.json())
        except ValueError:
            logger.warning("réponse headless illisible", extra={"event": "headless_delegation"})
            return _failed()
