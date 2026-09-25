"""Résout, pour un site, les jetons GA4 / Search Console à partir des liaisons
`website_google_links` (même logique que `RealAuditProbe`)."""

from __future__ import annotations

from uuid import UUID

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import ConnectionStatus, ResourceType
from app.models.google_connection import GoogleConnection
from app.models.website import Website
from app.models.website_google_link import WebsiteGoogleLink
from app.security.token_crypto import TokenCipher, TokenCryptoError
from app.services.connections import decrypt_refresh_token
from app.services.google_oauth import GoogleOAuthClient, GoogleOAuthError, InvalidGrantError
from app.services.measurement.google_reader import HttpGoogleReader


async def access_token_for(
    connection: GoogleConnection,
    oauth: GoogleOAuthClient,
    cipher: TokenCipher,
    cache: dict[UUID, str | None],
) -> str | None:
    if connection.id in cache:
        return cache[connection.id]
    token: str | None = None
    if connection.status == ConnectionStatus.ACTIVE:
        try:
            refresh_token = decrypt_refresh_token(connection, cipher=cipher)
            response = await oauth.refresh_access_token(refresh_token=refresh_token)
            token = response.access_token
        except InvalidGrantError:
            connection.status = ConnectionStatus.NEEDS_REAUTH
        except (GoogleOAuthError, TokenCryptoError, httpx.HTTPError):
            token = None
    cache[connection.id] = token
    return token


async def build_reader(
    session: AsyncSession,
    website: Website,
    *,
    oauth: GoogleOAuthClient,
    cipher: TokenCipher,
    http_client: httpx.AsyncClient | None = None,
) -> HttpGoogleReader:
    rows = (
        (
            await session.execute(
                select(WebsiteGoogleLink, GoogleConnection)
                .join(
                    GoogleConnection,
                    WebsiteGoogleLink.google_connection_id == GoogleConnection.id,
                )
                .where(
                    WebsiteGoogleLink.website_id == website.id,
                    WebsiteGoogleLink.resource_type.in_(
                        (ResourceType.GA4_PROPERTY, ResourceType.GSC_SITE)
                    ),
                )
            )
        )
        .tuples()
        .all()
    )

    cache: dict[UUID, str | None] = {}
    ga4_token: str | None = None
    ga4_property: str | None = None
    gsc_token: str | None = None
    gsc_site: str | None = None
    gsc_state = "not_linked"
    for link, connection in rows:
        token = await access_token_for(connection, oauth, cipher, cache)
        if link.resource_type == ResourceType.GA4_PROPERTY:
            ga4_property, ga4_token = link.resource_id, token
        else:
            gsc_site, gsc_token = link.resource_id, token
            gsc_state = "linked" if token else "needs_reauth"

    return HttpGoogleReader(
        ga4_token=ga4_token,
        ga4_property=ga4_property,
        gsc_token=gsc_token,
        gsc_site=gsc_site,
        gsc_state=gsc_state,
        client=http_client,
    )
