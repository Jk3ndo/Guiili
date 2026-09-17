"""Adaptateur Google OAuth reel (httpx). Non couvert par les tests unitaires :
la suite tourne en `GOOGLE_OAUTH_MOCK=true`. Ce client n'est jamais instancie
pendant les tests.
"""

from __future__ import annotations

from urllib.parse import urlencode

import httpx

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
    TokenExchangeError,
)

_AUTHORIZE = "https://accounts.google.com/o/oauth2/v2/auth"
_TOKEN = "https://oauth2.googleapis.com/token"
_REVOKE = "https://oauth2.googleapis.com/revoke"
_USERINFO = "https://openidconnect.googleapis.com/v1/userinfo"
_GA4_SUMMARIES = "https://analyticsadmin.googleapis.com/v1beta/accountSummaries"
_GTM_ACCOUNTS = "https://tagmanager.googleapis.com/tagmanager/v2/accounts"
_GSC_SITES = "https://searchconsole.googleapis.com/webmasters/v3/sites"

_TIMEOUT = httpx.Timeout(15.0)


def _token_response(payload: dict) -> GoogleTokenResponse:
    return GoogleTokenResponse(
        access_token=payload["access_token"],
        refresh_token=payload.get("refresh_token"),
        expires_in=int(payload.get("expires_in", 0)),
        scopes=tuple(payload.get("scope", "").split()),
        token_type=payload.get("token_type", "Bearer"),
        id_token=payload.get("id_token"),
    )


class RealGoogleOAuthClient(GoogleOAuthClient):
    def __init__(self, *, client_id: str, client_secret: str, redirect_uri: str) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._redirect_uri = redirect_uri

    def build_authorization_url(
        self,
        *,
        state: str,
        code_challenge: str,
        login_hint: str | None = None,
        scopes: tuple[str, ...] = GOOGLE_LOGIN_SCOPES,
        redirect_uri: str | None = None,
    ) -> str:
        params = {
            "response_type": "code",
            "client_id": self._client_id,
            "redirect_uri": redirect_uri or self._redirect_uri,
            "scope": " ".join(scopes),
            "state": state,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
            "access_type": "offline",
            "prompt": "consent",
            "include_granted_scopes": "true",
        }
        if login_hint:
            params["login_hint"] = login_hint
        return f"{_AUTHORIZE}?{urlencode(params)}"

    async def _post_token(self, form: dict) -> GoogleTokenResponse:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as http:
            resp = await http.post(_TOKEN, data=form)
        if resp.status_code == 400 and resp.json().get("error") == "invalid_grant":
            raise InvalidGrantError("Google a repondu invalid_grant")
        if resp.status_code >= 400:
            raise TokenExchangeError(f"token endpoint {resp.status_code}: {resp.text}")
        return _token_response(resp.json())

    async def exchange_code(
        self, *, code: str, code_verifier: str, redirect_uri: str | None = None
    ) -> GoogleTokenResponse:
        return await self._post_token(
            {
                "grant_type": "authorization_code",
                "code": code,
                "code_verifier": code_verifier,
                "client_id": self._client_id,
                "client_secret": self._client_secret,
                # Doit etre IDENTIQUE a celui envoye a l'autorisation, sinon
                # Google repond redirect_uri_mismatch.
                "redirect_uri": redirect_uri or self._redirect_uri,
            }
        )

    async def refresh_access_token(self, *, refresh_token: str) -> GoogleTokenResponse:
        return await self._post_token(
            {
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": self._client_id,
                "client_secret": self._client_secret,
            }
        )

    async def fetch_userinfo(self, *, access_token: str) -> GoogleUserInfo:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as http:
            resp = await http.get(_USERINFO, headers={"Authorization": f"Bearer {access_token}"})
        resp.raise_for_status()
        data = resp.json()
        return GoogleUserInfo(
            sub=data["sub"],
            email=data["email"],
            email_verified=bool(data.get("email_verified", False)),
            name=data.get("name"),
        )

    async def discover_resources(self, *, access_token: str) -> DiscoveredResources:
        headers = {"Authorization": f"Bearer {access_token}"}
        async with httpx.AsyncClient(timeout=_TIMEOUT, headers=headers) as http:
            ga4 = await self._discover_ga4(http)
            gtm = await self._discover_gtm(http)
            gsc = await self._discover_gsc(http)
        return DiscoveredResources(
            ga4_properties=tuple(ga4),
            gtm_containers=tuple(gtm),
            gsc_sites=tuple(gsc),
        )

    @staticmethod
    async def _discover_ga4(http: httpx.AsyncClient) -> list[Ga4Property]:
        resp = await http.get(_GA4_SUMMARIES, params={"pageSize": 200})
        resp.raise_for_status()
        out: list[Ga4Property] = []
        for summary in resp.json().get("accountSummaries", []):
            for prop in summary.get("propertySummaries", []):
                out.append(
                    Ga4Property(
                        resource_id=prop["property"],
                        display_name=prop.get("displayName", prop["property"]),
                        account=summary["account"],
                        account_display_name=summary.get("displayName", summary["account"]),
                    )
                )
        return out

    @staticmethod
    async def _discover_gtm(http: httpx.AsyncClient) -> list[GtmContainer]:
        accounts = (await http.get(_GTM_ACCOUNTS)).json().get("account", [])
        out: list[GtmContainer] = []
        for account in accounts:
            account_id = account["accountId"]
            containers = (
                (await http.get(f"{_GTM_ACCOUNTS}/{account_id}/containers"))
                .json()
                .get("container", [])
            )
            for container in containers:
                out.append(
                    GtmContainer(
                        resource_id=container["publicId"],
                        display_name=container.get("name", container["publicId"]),
                        account_id=account_id,
                        container_id=container["containerId"],
                    )
                )
        return out

    @staticmethod
    async def _discover_gsc(http: httpx.AsyncClient) -> list[GscSite]:
        resp = await http.get(_GSC_SITES)
        resp.raise_for_status()
        return [
            GscSite(
                resource_id=entry["siteUrl"],
                permission_level=entry.get("permissionLevel", "siteUnverifiedUser"),
            )
            for entry in resp.json().get("siteEntry", [])
        ]

    async def revoke(self, *, token: str) -> None:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as http:
            await http.post(_REVOKE, data={"token": token})
