"""Jetons du compte de service d'exécution, lus sur le serveur de métadonnées de Cloud
Run (aucune bibliothèque Google, aucun fichier de clé). Jamais appelé en test : les
tests injectent un client httpx factice."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Protocol

import httpx

_BASE = "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default"
_HEADERS = {"Metadata-Flavor": "Google"}
_TIMEOUT = httpx.Timeout(5.0)
_MARGIN_SECONDS = 60.0
# Un jeton d'identité Google vit une heure ; on le renouvelle au bout de 50 minutes.
_IDENTITY_TTL_SECONDS = 3000.0


class MetadataError(Exception):
    """Jeton indisponible (hors Cloud Run, serveur de métadonnées en erreur)."""


class AccessTokenProvider(Protocol):
    async def access_token(self) -> str: ...


class IdentityTokenProvider(Protocol):
    async def identity_token(self, audience: str) -> str: ...


class MetadataTokenProvider:
    def __init__(
        self,
        *,
        client: httpx.AsyncClient | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._client = client
        self._clock = clock
        self._access: tuple[str, float] | None = None
        self._identity: dict[str, tuple[str, float]] = {}

    async def _get(self, path: str, params: dict[str, str] | None = None) -> httpx.Response:
        owns = self._client is None
        http = self._client or httpx.AsyncClient(timeout=_TIMEOUT)
        try:
            response = await http.get(f"{_BASE}{path}", params=params, headers=_HEADERS)
        except httpx.HTTPError:
            raise MetadataError("serveur de métadonnées injoignable") from None
        finally:
            if owns:
                await http.aclose()
        if response.status_code != 200:
            raise MetadataError(f"serveur de métadonnées : HTTP {response.status_code}")
        return response

    async def access_token(self) -> str:
        now = self._clock()
        if self._access is not None and self._access[1] - _MARGIN_SECONDS > now:
            return self._access[0]
        response = await self._get("/token")
        try:
            payload = response.json()
            token, expires_in = str(payload["access_token"]), float(payload["expires_in"])
        except (ValueError, KeyError, TypeError):
            raise MetadataError("réponse de jeton illisible") from None
        self._access = (token, now + expires_in)
        return token

    async def identity_token(self, audience: str) -> str:
        now = self._clock()
        cached = self._identity.get(audience)
        if cached is not None and cached[1] > now:
            return cached[0]
        response = await self._get("/identity", {"audience": audience, "format": "full"})
        token = response.text.strip()
        if not token:
            raise MetadataError("jeton d'identité vide")
        self._identity[audience] = (token, now + _IDENTITY_TTL_SECONDS)
        return token
