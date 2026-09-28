"""Vérification des jetons d'identité (OIDC) Google reçus par les routes internes.

Contrôles : signature RS256 avec une clé publique Google (JWKS, mise en cache une
heure, relue une fois si l'identifiant de clé est inconnu), audience, expiration,
émetteur Google, e-mail vérifié et présent dans la liste des appelants autorisés
(comptes de service de Cloud Scheduler, de Cloud Tasks et de l'API). Sans audience ou
sans liste d'appelants, tout est refusé."""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from typing import Any

import httpx
import jwt

GOOGLE_ISSUERS = frozenset({"https://accounts.google.com", "accounts.google.com"})
GOOGLE_CERTS_URL = "https://www.googleapis.com/oauth2/v3/certs"
_TIMEOUT = httpx.Timeout(5.0)
# Un identifiant de clé inconnu relit les JWKS, mais au plus une fois par intervalle : sinon
# un appelant anonyme pourrait déclencher un appel sortant à chaque requête.
_MIN_REFRESH_SECONDS = 30.0

JwksFetcher = Callable[[], Awaitable[dict[str, Any]]]


class OidcError(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True, slots=True)
class OidcIdentity:
    email: str
    subject: str


async def fetch_google_jwks(client: httpx.AsyncClient | None = None) -> dict[str, Any]:
    owns = client is None
    http = client or httpx.AsyncClient(timeout=_TIMEOUT)
    try:
        response = await http.get(GOOGLE_CERTS_URL)
        response.raise_for_status()
        payload = response.json()
    except (httpx.HTTPError, ValueError):
        raise OidcError("jwks_unavailable") from None
    finally:
        if owns:
            await http.aclose()
    if not isinstance(payload, dict):
        raise OidcError("jwks_unavailable")
    return payload


class OidcVerifier:
    def __init__(
        self,
        *,
        audience: str,
        allowed_emails: Iterable[str],
        fetch_jwks: JwksFetcher = fetch_google_jwks,
        cache_seconds: float = 3600.0,
        clock: Callable[[], float] = time.monotonic,
        leeway_seconds: int = 30,
    ) -> None:
        self._audience = audience
        self._allowed = frozenset(email.lower() for email in allowed_emails)
        self._fetch = fetch_jwks
        self._cache_seconds = cache_seconds
        self._clock = clock
        self._leeway = leeway_seconds
        self._keys: dict[str, Any] = {}
        self._loaded_at: float | None = None

    async def _refresh(self) -> None:
        payload = await self._fetch()
        keys: dict[str, Any] = {}
        for entry in payload.get("keys", []) if isinstance(payload.get("keys"), list) else []:
            if not isinstance(entry, dict) or not isinstance(entry.get("kid"), str):
                continue
            try:
                keys[entry["kid"]] = jwt.PyJWK(entry).key
            except jwt.PyJWTError:
                continue
        self._keys = keys
        self._loaded_at = self._clock()

    async def _key(self, kid: str) -> Any:
        age = None if self._loaded_at is None else self._clock() - self._loaded_at
        stale = age is None or age > self._cache_seconds
        unknown_kid_refresh_allowed = age is None or age >= _MIN_REFRESH_SECONDS
        if stale or (kid not in self._keys and unknown_kid_refresh_allowed):
            await self._refresh()
        key = self._keys.get(kid)
        if key is None:
            raise OidcError("unknown_key")
        return key

    async def verify(self, token: str) -> OidcIdentity:
        if not self._audience or not self._allowed:
            raise OidcError("not_configured")
        try:
            header = jwt.get_unverified_header(token)
        except jwt.PyJWTError:
            raise OidcError("invalid_token") from None
        kid = header.get("kid")
        if header.get("alg") != "RS256" or not isinstance(kid, str):
            raise OidcError("invalid_token")
        key = await self._key(kid)
        try:
            claims = jwt.decode(
                token,
                key,
                algorithms=["RS256"],
                audience=self._audience,
                leeway=self._leeway,
                options={"require": ["exp", "iat", "aud", "iss"]},
            )
        except jwt.PyJWTError:
            raise OidcError("invalid_token") from None
        if claims.get("iss") not in GOOGLE_ISSUERS:
            raise OidcError("wrong_issuer")
        if claims.get("email_verified") is not True:
            raise OidcError("email_not_verified")
        email = str(claims.get("email", "")).lower()
        if email not in self._allowed:
            raise OidcError("caller_not_allowed")
        return OidcIdentity(email=email, subject=str(claims.get("sub", "")))
