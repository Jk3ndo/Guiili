"""GET /google/resources : decouverte agregee sur les connexions actives."""

from urllib.parse import parse_qs, urlparse
from uuid import uuid4

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.enums import ConnectionStatus, StackKind
from app.models.google_connection import GoogleConnection
from app.models.user import User
from app.security.token_crypto import load_token_cipher
from app.services.connections import upsert_google_connection
from app.services.google_oauth.base import GoogleTokenResponse, GoogleUserInfo
from app.services.stack_detector import StackDetection, StackGuess
from tests.conftest import owner_workspace_id


def _query(url: str) -> dict[str, str]:
    return {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}

_SCOPES = ("openid", "email", "https://www.googleapis.com/auth/analytics.readonly")


async def _make_connection(
    session: AsyncSession, *, user: User, sub: str, email: str, refresh: str
) -> GoogleConnection:
    cipher = load_token_cipher(get_settings())
    return await upsert_google_connection(
        session,
        workspace_id=await owner_workspace_id(session, user),
        userinfo=GoogleUserInfo(sub=sub, email=email),
        token=GoogleTokenResponse(
            access_token="at", refresh_token=refresh, expires_in=3599, scopes=_SCOPES
        ),
        cipher=cipher,
    )


async def test_requires_authentication(db_client: AsyncClient) -> None:
    assert (await db_client.get("/api/v1/google/resources")).status_code == 401


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

    resp = await client.get("/api/v1/google/resources")
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

    resp = await client.get("/api/v1/google/resources")
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


async def test_resources_summary_includes_scopes_and_last_refresh(
    authed_client: tuple[AsyncClient, "User"], db_session: AsyncSession,
) -> None:
    client, user = authed_client
    ws_id = await owner_workspace_id(db_session, user)

    # Etablit une connexion active via le vrai flow HTTP start->callback
    # (meme sequence que test_connections_google_callback.py::test_callback_creates_connection,
    # ecrite en Task 5 — reprise ici telle quelle, pas de nouvel helper partage
    # cree pour eviter d'introduire une dependance entre fichiers de test).
    start = await client.get(
        "/api/v1/connections/google/start", params={"workspace_id": str(ws_id)}
    )
    state = _query(start.json()["authorization_url"])["state"]
    await client.get(
        "/api/v1/connections/google/callback",
        params={"code": "mock:client_perso", "state": state},
        follow_redirects=False,
    )

    resp = await client.get("/api/v1/google/resources")
    summary = resp.json()["connections"][0]
    assert summary["granted_scopes"] == [
        "openid", "email",
        "https://www.googleapis.com/auth/analytics.readonly",
    ]  # scopes de la fixture mock "client_perso", voir app/services/google_oauth/mock.py
    assert summary["last_refreshed_at"] is not None


async def test_website_google_links_returns_current_links(
    authed_client: tuple[AsyncClient, "User"], db_session: AsyncSession, monkeypatch,
) -> None:
    # Mock detect_stack to avoid needing real detection
    async def _mock_detect(url: str, *, allow_insecure: bool = False):
        return StackDetection(
            StackKind.NEXTJS,
            ("next-static", "next-data"),
            0.85,
            candidates=(StackGuess("Vercel", "en-tetes Vercel"),),
        )

    monkeypatch.setattr("app.services.stack_detector.detect_stack", _mock_detect)

    client, _ = authed_client
    site_resp = await client.post("/api/v1/websites", json={"name": "L", "domain": "gg-links.test"})
    site_id = site_resp.json()["id"]

    resp = await client.get(f"/api/v1/websites/{site_id}/google-links")
    assert resp.status_code == 200
    assert resp.json() == []  # aucune liaison pour l'instant


async def test_website_google_links_requires_membership(
    authed_client: tuple[AsyncClient, "User"],
) -> None:
    client, _ = authed_client
    resp = await client.get(f"/api/v1/websites/{uuid4()}/google-links")
    assert resp.status_code == 404
