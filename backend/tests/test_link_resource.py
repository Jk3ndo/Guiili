"""POST /websites/{id}/link-resource : liaison explicite, dont multi-comptes."""

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.google_connection import GoogleConnection
from app.models.user import User
from app.models.website import Website
from app.models.website_google_link import WebsiteGoogleLink
from app.security.token_crypto import load_token_cipher
from app.services.connections import upsert_google_connection
from app.services.google_oauth.base import GoogleTokenResponse, GoogleUserInfo


async def _connection(session: AsyncSession, *, user: User, sub: str) -> GoogleConnection:
    return await upsert_google_connection(
        session,
        user_id=user.id,
        userinfo=GoogleUserInfo(sub=sub, email=f"{sub}@gmail.com"),
        token=GoogleTokenResponse(
            access_token="at",
            refresh_token=f"mock-refresh|{sub}",
            expires_in=1,
            scopes=("openid",),
        ),
        cipher=load_token_cipher(get_settings()),
    )


async def _website(session: AsyncSession, *, user: User, domain: str) -> Website:
    site = Website(user_id=user.id, domain=domain, display_name=domain)
    session.add(site)
    await session.flush()
    return site


async def test_two_connections_one_website(
    authed_client: tuple[AsyncClient, User], db_session: AsyncSession
) -> None:
    client, user = authed_client
    conn_a = await _connection(db_session, user=user, sub="acct-a")
    conn_b = await _connection(db_session, user=user, sub="acct-b")
    site = await _website(db_session, user=user, domain="monsite.com")

    ga4 = await client.post(
        f"/api/v1/websites/{site.id}/link-resource",
        json={
            "google_connection_id": str(conn_a.id),
            "resource_type": "ga4_property",
            "resource_id": "properties/447213908",
            "resource_display_name": "Boutique Prod",
        },
    )
    assert ga4.status_code == 201, ga4.text

    gtm = await client.post(
        f"/api/v1/websites/{site.id}/link-resource",
        json={
            "google_connection_id": str(conn_b.id),
            "resource_type": "gtm_container",
            "resource_id": "GTM-PK2X9QM",
        },
    )
    assert gtm.status_code == 201, gtm.text

    links = (
        (
            await db_session.execute(
                select(WebsiteGoogleLink).where(WebsiteGoogleLink.website_id == site.id)
            )
        )
        .scalars()
        .all()
    )
    assert len(links) == 2
    by_type = {link.resource_type.value: link for link in links}
    assert by_type["ga4_property"].google_connection_id == conn_a.id
    assert by_type["gtm_container"].google_connection_id == conn_b.id
    # deux connexions Google differentes, un seul site
    assert (
        by_type["ga4_property"].google_connection_id
        != by_type["gtm_container"].google_connection_id
    )


async def test_relink_same_type_replaces_previous(
    authed_client: tuple[AsyncClient, User], db_session: AsyncSession
) -> None:
    client, user = authed_client
    conn = await _connection(db_session, user=user, sub="acct-c")
    site = await _website(db_session, user=user, domain="swap.com")

    for resource_id in ("properties/111", "properties/222"):
        resp = await client.post(
            f"/api/v1/websites/{site.id}/link-resource",
            json={
                "google_connection_id": str(conn.id),
                "resource_type": "ga4_property",
                "resource_id": resource_id,
            },
        )
        assert resp.status_code == 201

    links = (
        (
            await db_session.execute(
                select(WebsiteGoogleLink).where(WebsiteGoogleLink.website_id == site.id)
            )
        )
        .scalars()
        .all()
    )
    assert len(links) == 1
    assert links[0].resource_id == "properties/222"


async def test_rejects_website_of_another_user(
    authed_client: tuple[AsyncClient, User], db_session: AsyncSession, make_user
) -> None:
    client, user = authed_client
    conn = await _connection(db_session, user=user, sub="acct-d")
    stranger = await make_user(sub="stranger")
    foreign_site = await _website(db_session, user=stranger, domain="notyours.com")

    resp = await client.post(
        f"/api/v1/websites/{foreign_site.id}/link-resource",
        json={
            "google_connection_id": str(conn.id),
            "resource_type": "ga4_property",
            "resource_id": "properties/999",
        },
    )
    assert resp.status_code == 404


async def test_rejects_connection_of_another_user(
    authed_client: tuple[AsyncClient, User], db_session: AsyncSession, make_user
) -> None:
    client, user = authed_client
    site = await _website(db_session, user=user, domain="mine.com")
    stranger = await make_user(sub="stranger-2")
    foreign_conn = await _connection(db_session, user=stranger, sub="acct-foreign")

    resp = await client.post(
        f"/api/v1/websites/{site.id}/link-resource",
        json={
            "google_connection_id": str(foreign_conn.id),
            "resource_type": "ga4_property",
            "resource_id": "properties/1",
        },
    )
    assert resp.status_code == 400


async def test_requires_authentication(db_client: AsyncClient) -> None:
    resp = await db_client.post(
        "/api/v1/websites/00000000-0000-0000-0000-000000000000/link-resource",
        json={
            "google_connection_id": "00000000-0000-0000-0000-000000000000",
            "resource_type": "ga4_property",
            "resource_id": "x",
        },
    )
    assert resp.status_code == 401
