"""RealAuditProbe : combine PageSpeed + GSC + GA4 pour les ressources associees.

Un seul `httpx.MockTransport` route les trois APIs par URL ; l'adaptateur OAuth
est un stub local. Zero appel reseau.
"""

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.enums import ConnectionStatus, ResourceType, StackKind
from app.models.user import User
from app.models.website import Website
from app.models.website_google_link import WebsiteGoogleLink
from app.security.token_crypto import load_token_cipher
from app.services.audit_probe import RealAuditProbe
from app.services.connections import upsert_google_connection
from app.services.google_oauth import GoogleTokenResponse, GoogleUserInfo, InvalidGrantError
from tests.conftest import owner_workspace_id

_CIPHER = load_token_cipher(get_settings())
_SCOPES = (
    "openid",
    "email",
    "https://www.googleapis.com/auth/analytics.readonly",
    "https://www.googleapis.com/auth/webmasters.readonly",
)

_GA4_PAYLOAD = {
    "rows": [
        {
            "dimensionValues": [{"value": "page_view"}],
            "metricValues": [{"value": "48000"}, {"value": "0"}, {"value": "0"}],
        },
        {
            "dimensionValues": [{"value": "purchase"}],
            "metricValues": [{"value": "300"}, {"value": "0"}, {"value": "0"}],
        },
    ]
}
_GSC_PAYLOAD = {
    "rows": [
        {"keys": ["https://shop.test/collections/all"], "clicks": 210, "impressions": 5000.0},
        {"keys": ["https://shop.test/blog/guide"], "clicks": 40, "impressions": 900.0},
    ]
}


def _router(*, gsc_status: int = 200, ga4_status: int = 200):
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "runPagespeed" in url:
            return httpx.Response(
                200,
                json={
                    "lighthouseResult": {
                        "categories": {"performance": {"score": 0.5}},
                        "audits": {
                            "largest-contentful-paint": {"numericValue": 3200},
                            "cumulative-layout-shift": {"numericValue": 0.05},
                        },
                    }
                },
            )
        if "searchAnalytics/query" in url:
            return httpx.Response(gsc_status, json=_GSC_PAYLOAD)
        if ":runReport" in url:
            return httpx.Response(ga4_status, json=_GA4_PAYLOAD)
        return httpx.Response(404, json={})

    return handler


class _StubOAuth:
    """Implemente uniquement ce que RealAuditProbe appelle."""

    def __init__(self, *, revoked: bool = False) -> None:
        self._revoked = revoked

    async def refresh_access_token(self, *, refresh_token: str) -> GoogleTokenResponse:
        if self._revoked or refresh_token.endswith("|revoked"):
            raise InvalidGrantError("refresh token revoque")
        return GoogleTokenResponse(
            access_token="fresh-access-token",
            refresh_token=None,
            expires_in=3599,
            scopes=_SCOPES,
        )


async def _website(session: AsyncSession, user: User) -> Website:
    workspace_id = await owner_workspace_id(session, user)
    site = Website(workspace_id=workspace_id, domain="shop.test", display_name="Shop")
    session.add(site)
    await session.flush()
    return site


async def _connection(session: AsyncSession, user: User, *, refresh: str = "rt-live"):
    return await upsert_google_connection(
        session,
        workspace_id=await owner_workspace_id(session, user),
        userinfo=GoogleUserInfo(sub="g-sub-1", email="owner@gmail.com"),
        token=GoogleTokenResponse(
            access_token="at", refresh_token=refresh, expires_in=3599, scopes=_SCOPES
        ),
        cipher=_CIPHER,
    )


async def _link(session, site, connection, resource_type: ResourceType, resource_id: str):
    link = WebsiteGoogleLink(
        website_id=site.id,
        google_connection_id=connection.id,
        resource_type=resource_type,
        resource_id=resource_id,
    )
    session.add(link)
    await session.flush()
    return link


async def test_combines_pagespeed_gsc_ga4(db_session: AsyncSession, make_user) -> None:
    user = await make_user(sub="p3-1")
    site = await _website(db_session, user)
    connection = await _connection(db_session, user)
    await _link(db_session, site, connection, ResourceType.GA4_PROPERTY, "properties/447213908")
    await _link(db_session, site, connection, ResourceType.GSC_SITE, "sc-domain:shop.test")

    async with httpx.AsyncClient(transport=httpx.MockTransport(_router())) as http:
        probe = RealAuditProbe(http_client=http, oauth_client=_StubOAuth(), cipher=_CIPHER)
        data = await probe.collect(website=site, stack=StackKind.NEXTJS, session=db_session)

    assert data.cwv.lcp_ms == 3200  # PageSpeed labo
    # GA4 : purchase sans revenu -> parametres manquants
    assert data.ga4.purchase_missing_params == ("value", "currency")
    assert data.ga4.degraded is False
    # GSC : URLs reelles remontees
    assert data.gsc.sample_urls[0].path == "/collections/all"
    assert data.gsc.degraded is False


async def test_no_linked_resources_keeps_google_signals_neutral(
    db_session: AsyncSession, make_user
) -> None:
    user = await make_user(sub="p3-2")
    site = await _website(db_session, user)

    async with httpx.AsyncClient(transport=httpx.MockTransport(_router())) as http:
        probe = RealAuditProbe(http_client=http, oauth_client=_StubOAuth(), cipher=_CIPHER)
        data = await probe.collect(website=site, stack=StackKind.NEXTJS, session=db_session)

    assert data.ga4.score == 0
    assert data.gsc.score == 0
    assert data.cwv.lcp_ms == 3200  # PageSpeed reste appele


async def test_revoked_token_degrades_and_flips_connection(
    db_session: AsyncSession, make_user
) -> None:
    user = await make_user(sub="p3-3")
    site = await _website(db_session, user)
    connection = await _connection(db_session, user, refresh="rt|revoked")
    await _link(db_session, site, connection, ResourceType.GSC_SITE, "sc-domain:shop.test")
    await _link(db_session, site, connection, ResourceType.GA4_PROPERTY, "properties/1")

    async with httpx.AsyncClient(transport=httpx.MockTransport(_router())) as http:
        probe = RealAuditProbe(http_client=http, oauth_client=_StubOAuth(), cipher=_CIPHER)
        data = await probe.collect(website=site, stack=StackKind.NEXTJS, session=db_session)

    assert data.gsc.degraded is True
    assert data.gsc.connection_stale_days == 30
    assert data.ga4.degraded is True
    # la connexion est marquee a re-autoriser (persiste au flush)
    assert connection.status is ConnectionStatus.NEEDS_REAUTH
    await db_session.flush()


async def test_gsc_quota_error_degrades_only_gsc(db_session: AsyncSession, make_user) -> None:
    user = await make_user(sub="p3-4")
    site = await _website(db_session, user)
    connection = await _connection(db_session, user)
    await _link(db_session, site, connection, ResourceType.GSC_SITE, "sc-domain:shop.test")
    await _link(db_session, site, connection, ResourceType.GA4_PROPERTY, "properties/447213908")

    router = _router(gsc_status=403)
    async with httpx.AsyncClient(transport=httpx.MockTransport(router)) as http:
        probe = RealAuditProbe(http_client=http, oauth_client=_StubOAuth(), cipher=_CIPHER)
        data = await probe.collect(website=site, stack=StackKind.NEXTJS, session=db_session)

    assert data.gsc.degraded is True
    assert data.ga4.degraded is False
    assert data.ga4.purchase_missing_params == ("value", "currency")


@pytest.mark.parametrize("has_session", [False, True])
async def test_without_oauth_client_stays_pagespeed_only(
    db_session: AsyncSession, make_user, has_session: bool
) -> None:
    user = await make_user(sub=f"p3-noauth-{has_session}")
    site = await _website(db_session, user)

    async with httpx.AsyncClient(transport=httpx.MockTransport(_router())) as http:
        probe = RealAuditProbe(http_client=http)  # ni oauth ni cipher
        data = await probe.collect(
            website=site,
            stack=StackKind.NEXTJS,
            session=db_session if has_session else None,
        )

    assert data.cwv.lcp_ms == 3200
    assert data.ga4.score == 0
    assert data.gsc.score == 0
