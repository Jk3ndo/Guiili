"""Adaptateur Google OAuth de test — fixtures deterministes, zero reseau.

Active quand `GOOGLE_OAUTH_MOCK=true`. Les identites et ressources refletent
`frontend/lib/mock/connections.ts` (workspace « Boutique Verte »).

Convention de pilotage depuis les tests :
- `code` = ``"mock:<cle_fixture>"`` (ou tout autre chose -> fixture par defaut).
- `refresh_token` inconnu ou finissant par ``"|revoked"`` -> `InvalidGrantError`.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlencode

from app.services.google_oauth.base import (
    DiscoveredResources,
    Ga4Property,
    GoogleOAuthClient,
    GoogleTokenResponse,
    GoogleUserInfo,
    GscSite,
    GtmContainer,
    InvalidGrantError,
)

_ANALYTICS = "https://www.googleapis.com/auth/analytics.readonly"
_WEBMASTERS = "https://www.googleapis.com/auth/webmasters.readonly"


@dataclass(frozen=True, slots=True)
class MockIdentity:
    key: str
    sub: str
    email: str
    name: str
    scopes: tuple[str, ...]
    resources: DiscoveredResources


MOCK_FIXTURES: dict[str, MockIdentity] = {
    "dev_agence": MockIdentity(
        key="dev_agence",
        sub="google-sub-dev-agence",
        email="dev.agence@gmail.com",
        name="Agence Dev",
        scopes=("openid", "email", _ANALYTICS, _WEBMASTERS),
        resources=DiscoveredResources(
            ga4_properties=(
                Ga4Property(
                    resource_id="properties/338100771",
                    display_name="Blog éditorial",
                    account="accounts/6012840193",
                    account_display_name="Agence — accès délégué",
                ),
            ),
            gtm_containers=(
                GtmContainer(
                    resource_id="GTM-PK2X9QM",
                    display_name="Web Container",
                    account_id="6012840193",
                    container_id="198765432",
                ),
                GtmContainer(
                    resource_id="GTM-9KX2P0M",
                    display_name="Serveur (sGTM)",
                    account_id="6012840193",
                    container_id="205551903",
                ),
            ),
            gsc_sites=(
                GscSite(resource_id="sc-domain:boutique-verte.fr", permission_level="siteOwner"),
                GscSite(resource_id="https://boutique-verte.fr/", permission_level="siteFullUser"),
            ),
        ),
    ),
    "client_perso": MockIdentity(
        key="client_perso",
        sub="google-sub-client-perso",
        email="client.perso@gmail.com",
        name="Client Perso",
        scopes=("openid", "email", _ANALYTICS),
        resources=DiscoveredResources(
            ga4_properties=(
                Ga4Property(
                    resource_id="properties/447213908",
                    display_name="Boutique Prod",
                    account="accounts/6009114772",
                    account_display_name="Compte du client",
                ),
                Ga4Property(
                    resource_id="properties/501882145",
                    display_name="Boutique Staging",
                    account="accounts/6009114772",
                    account_display_name="Compte du client",
                ),
            ),
        ),
    ),
}

_DEFAULT_KEY = "dev_agence"
_ACCESS_PREFIX = "mock-access|"
_REFRESH_PREFIX = "mock-refresh|"


def _identity_from_code(code: str) -> MockIdentity:
    if code.startswith("mock:"):
        return MOCK_FIXTURES.get(code.removeprefix("mock:"), MOCK_FIXTURES[_DEFAULT_KEY])
    return MOCK_FIXTURES[_DEFAULT_KEY]


def _identity_from_access_token(access_token: str) -> MockIdentity:
    key = access_token.removeprefix(_ACCESS_PREFIX)
    try:
        return MOCK_FIXTURES[key]
    except KeyError as exc:
        raise InvalidGrantError(f"access token mock inconnu : {access_token!r}") from exc


class MockGoogleOAuthClient(GoogleOAuthClient):
    def __init__(
        self,
        *,
        redirect_uri: str = "http://localhost:8000/auth/google/callback",
        client_id: str = "mock-client-id",
        authorize_endpoint: str = "https://accounts.google.com/o/oauth2/v2/auth",
    ) -> None:
        self._redirect_uri = redirect_uri
        self._client_id = client_id
        self._authorize_endpoint = authorize_endpoint

    def build_authorization_url(
        self, *, state: str, code_challenge: str, login_hint: str | None = None
    ) -> str:
        params = {
            "response_type": "code",
            "client_id": self._client_id,
            "redirect_uri": self._redirect_uri,
            "scope": "openid email",
            "state": state,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
            "access_type": "offline",
            "prompt": "consent",
            "include_granted_scopes": "true",
        }
        if login_hint:
            params["login_hint"] = login_hint
        return f"{self._authorize_endpoint}?{urlencode(params)}"

    async def exchange_code(self, *, code: str, code_verifier: str) -> GoogleTokenResponse:
        if not code_verifier:
            raise InvalidGrantError("code_verifier manquant")
        identity = _identity_from_code(code)
        return GoogleTokenResponse(
            access_token=_ACCESS_PREFIX + identity.key,
            refresh_token=_REFRESH_PREFIX + identity.sub,
            expires_in=3599,
            scopes=identity.scopes,
            id_token=f"mock-id-token|{identity.sub}",
        )

    async def refresh_access_token(self, *, refresh_token: str) -> GoogleTokenResponse:
        if refresh_token.endswith("|revoked"):
            raise InvalidGrantError("refresh token revoque")
        sub = refresh_token.removeprefix(_REFRESH_PREFIX)
        identity = next((item for item in MOCK_FIXTURES.values() if item.sub == sub), None)
        if identity is None:
            raise InvalidGrantError(f"refresh token mock inconnu : {refresh_token!r}")
        return GoogleTokenResponse(
            access_token=_ACCESS_PREFIX + identity.key,
            refresh_token=None,
            expires_in=3599,
            scopes=identity.scopes,
        )

    async def fetch_userinfo(self, *, access_token: str) -> GoogleUserInfo:
        identity = _identity_from_access_token(access_token)
        return GoogleUserInfo(
            sub=identity.sub,
            email=identity.email,
            email_verified=True,
            name=identity.name,
        )

    async def discover_resources(self, *, access_token: str) -> DiscoveredResources:
        return _identity_from_access_token(access_token).resources

    async def revoke(self, *, token: str) -> None:
        _ = token  # no-op : rien a revoquer cote mock
