"""GET /google/resources : decouverte agregee sur les connexions actives."""

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.enums import ConnectionStatus
from app.models.google_connection import GoogleConnection
from app.models.user import User
from app.security.token_crypto import load_token_cipher
from app.services.connections import upsert_google_connection
from app.services.google_oauth.base import GoogleTokenResponse, GoogleUserInfo

_SCOPES = ("openid", "email", "https://www.googleapis.com/auth/analytics.readonly")


async def _make_connection(
    session: AsyncSession, *, user: User, sub: str, email: str, refresh: str
) -> GoogleConnection:
    cipher = load_token_cipher(get_settings())
    return await upsert_google_connection(
        session,
        user_id=user.id,
        userinfo=GoogleUserInfo(sub=sub, email=email),
        token=GoogleTokenResponse(
            access_token="at", refresh_token=refresh, expires_in=3599, scopes=_SCOPES
        ),
        cipher=cipher,
    )


async def test_requires_authentication(db_client: AsyncClient) -> None:
    assert (await db_client.get("/google/resources")).status_code == 401


async def test_aggregates_resources_across_two_connections(
    authed_client: tuple[AsyncClient, User], db_session: AsyncSession
) -> None:
    client, user = authed_client
    await _make_connection(
        db_session,
        user=user,
        sub="google-sub-dev-agence",
        email="dev.agence@gmail.com",
        refresh="mock-refresh|google-sub-dev-agence",
    )
    await _make_connection(
        db_session,
        user=user,
        sub="google-sub-client-perso",
        email="client.perso@gmail.com",
        refresh="mock-refresh|google-sub-client-perso",
    )

    resp = await client.get("/google/resources")
    assert resp.status_code == 200, resp.text
    body = resp.json()

    ga4 = {p["resource_id"]: p for p in body["ga4_properties"]}
    assert {"properties/447213908", "properties/501882145", "properties/338100771"} <= set(ga4)
    # chaque ressource porte sa connexion source
    assert ga4["properties/447213908"]["source_email"] == "client.perso@gmail.com"
    assert ga4["properties/338100771"]["source_email"] == "dev.agence@gmail.com"

    gtm = {c["resource_id"] for c in body["gtm_containers"]}
    assert gtm == {"GTM-PK2X9QM", "GTM-9KX2P0M"}
    gsc = {s["resource_id"] for s in body["gsc_sites"]}
    assert "sc-domain:boutique-verte.fr" in gsc
    assert len(body["connections"]) == 2


async def test_revoked_connection_flips_to_needs_reauth(
    authed_client: tuple[AsyncClient, User], db_session: AsyncSession
) -> None:
    client, user = authed_client
    await _make_connection(
        db_session,
        user=user,
        sub="google-sub-dev-agence",
        email="dev.agence@gmail.com",
        refresh="mock-refresh|google-sub-dev-agence",
    )
    dead = await _make_connection(
        db_session,
        user=user,
        sub="ghost-sub",
        email="ghost@gmail.com",
        refresh="mock-refresh|ghost-sub|revoked",
    )

    resp = await client.get("/google/resources")
    assert resp.status_code == 200
    body = resp.json()

    # la connexion revoquee n'apporte aucune ressource
    assert all(
        r["source_connection_id"] != str(dead.id)
        for r in body["ga4_properties"] + body["gtm_containers"] + body["gsc_sites"]
    )
    # et son statut est persiste en needs_reauth
    await db_session.refresh(dead)
    assert dead.status == ConnectionStatus.NEEDS_REAUTH

    refreshed = (
        await db_session.execute(select(GoogleConnection).where(GoogleConnection.id == dead.id))
    ).scalar_one()
    assert refreshed.status == ConnectionStatus.NEEDS_REAUTH
