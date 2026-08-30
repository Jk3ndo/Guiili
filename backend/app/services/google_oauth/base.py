"""Contrat de l'adaptateur Google OAuth + types de transfert.

Deux implementations : `RealGoogleOAuthClient` (endpoints Google) et
`MockGoogleOAuthClient` (fixtures, aucun reseau). Le choix se fait via
`app.services.google_oauth.factory.get_google_oauth_client`.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field

# Scopes STRICTEMENT en lecture (aucun scope sensible/restreint -> pas de CASA).
GOOGLE_OAUTH_SCOPES: tuple[str, ...] = (
    "openid",
    "email",
    "https://www.googleapis.com/auth/analytics.readonly",
    "https://www.googleapis.com/auth/webmasters.readonly",
)


class GoogleOAuthError(Exception):
    """Base des erreurs de l'adaptateur."""


class InvalidGrantError(GoogleOAuthError):
    """Le code ou le refresh token a ete revoque / est expire (`invalid_grant`)."""


class TokenExchangeError(GoogleOAuthError):
    """Echec de l'echange de code / rafraichissement, hors `invalid_grant`."""


@dataclass(frozen=True, slots=True)
class GoogleTokenResponse:
    access_token: str
    expires_in: int
    scopes: tuple[str, ...]
    token_type: str = "Bearer"
    # Google n'emet un refresh token qu'au premier consentement (ou avec
    # prompt=consent). None lors d'un simple rafraichissement.
    refresh_token: str | None = None
    id_token: str | None = None


@dataclass(frozen=True, slots=True)
class GoogleUserInfo:
    sub: str
    email: str
    email_verified: bool = True
    name: str | None = None


@dataclass(frozen=True, slots=True)
class Ga4Property:
    # "properties/447213908"
    resource_id: str
    display_name: str
    account: str
    account_display_name: str


@dataclass(frozen=True, slots=True)
class GtmContainer:
    # "GTM-PK2X9QM"
    resource_id: str
    display_name: str
    account_id: str
    container_id: str


@dataclass(frozen=True, slots=True)
class GscSite:
    # "sc-domain:example.com" ou "https://example.com/"
    resource_id: str
    permission_level: str


@dataclass(frozen=True, slots=True)
class DiscoveredResources:
    ga4_properties: tuple[Ga4Property, ...] = field(default_factory=tuple)
    gtm_containers: tuple[GtmContainer, ...] = field(default_factory=tuple)
    gsc_sites: tuple[GscSite, ...] = field(default_factory=tuple)


class GoogleOAuthClient(abc.ABC):
    @abc.abstractmethod
    def build_authorization_url(
        self, *, state: str, code_challenge: str, login_hint: str | None = None
    ) -> str: ...

    @abc.abstractmethod
    async def exchange_code(self, *, code: str, code_verifier: str) -> GoogleTokenResponse: ...

    @abc.abstractmethod
    async def refresh_access_token(self, *, refresh_token: str) -> GoogleTokenResponse: ...

    @abc.abstractmethod
    async def fetch_userinfo(self, *, access_token: str) -> GoogleUserInfo: ...

    @abc.abstractmethod
    async def discover_resources(self, *, access_token: str) -> DiscoveredResources: ...

    @abc.abstractmethod
    async def revoke(self, *, token: str) -> None: ...
