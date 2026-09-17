"""Adaptateur Google OAuth de test — fixtures deterministes, zero reseau.

Active quand `GOOGLE_OAUTH_MOCK=true`. Les identites et ressources refletent
le jeu de demo historique du front (workspace « Boutique Verte »).

Convention de pilotage depuis les tests :
- `code` = ``"mock:<cle_fixture>"`` (ou tout autre chose -> fixture par defaut).
- `refresh_token` inconnu ou finissant par ``"|revoked"`` -> `InvalidGrantError`.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlencode

from app.services.google_oauth.base import (
    GOOGLE_LOGIN_SCOPES,
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
        redirect_uri: str = "http://127.0.0.1:8020/api/v1/auth/google/callback",
        client_id: str = "mock-client-id",
        authorize_endpoint: str | None = None,
        mock_identity_key: str = _DEFAULT_KEY,
    ) -> None:
        self._redirect_uri = redirect_uri
        self._client_id = client_id
        # Mode mock : zero reseau, y compris si un vrai navigateur suit ce lien.
        # Contrairement a une URL Google reelle, on pointe directement sur NOTRE
        # callback (le meme redirect_uri que le flow reel) avec un `code=mock:...`
        # deja pret a etre echange -- un clic reel sur "Continuer avec Google"
        # complete alors un login mock authentique en un aller-retour. Pointer
        # vers accounts.google.com (comme avant) fonctionnait pour les tests
        # (qui ne font qu'inspecter la query string, jamais la suivre), mais
        # faisait echouer un vrai clic navigateur avec `invalid_client` — le
        # `client_id` factice n'existe evidemment pas cote Google.
        #
        # On garde l'override BRUT (souvent None) au lieu de le figer sur
        # `redirect_uri` des la construction : la cible de l'auto-redirection
        # est calculee par appel, a partir du redirect_uri effectif, pour que
        # le mock suive le flow qui l'a initie (login OU connexion de donnees)
        # exactement comme le fera le client reel.
        self._authorize_endpoint_override = authorize_endpoint
        self._mock_identity_key = mock_identity_key

    def build_authorization_url(
        self,
        *,
        state: str,
        code_challenge: str,
        login_hint: str | None = None,
        scopes: tuple[str, ...] = GOOGLE_LOGIN_SCOPES,
        redirect_uri: str | None = None,
    ) -> str:
        effective_redirect_uri = redirect_uri or self._redirect_uri
        params = {
            "response_type": "code",
            "client_id": self._client_id,
            "redirect_uri": effective_redirect_uri,
            "scope": " ".join(scopes),
            "state": state,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
            "access_type": "offline",
            "prompt": "consent",
            "include_granted_scopes": "true",
            # Permet a notre propre callback de completer immediatement le
            # login mock quand cette URL est reellement suivie par un navigateur.
            "code": f"mock:{self._mock_identity_key}",
        }
        if login_hint:
            params["login_hint"] = login_hint
        authorize_endpoint = self._authorize_endpoint_override or effective_redirect_uri
        return f"{authorize_endpoint}?{urlencode(params)}"

    async def exchange_code(
        self, *, code: str, code_verifier: str, redirect_uri: str | None = None
    ) -> GoogleTokenResponse:
        # `redirect_uri` ignore : le mock derive tout du `code`. Google, lui,
        # verifie que l'autorisation et l'echange portent le meme redirect_uri.
        _ = redirect_uri
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
