"""GET /google/resources : decouverte agregee sur les connexions actives."""

from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    get_audit_probe,
    get_gtm_checker,
    get_live_stack_detector,
    get_tls_checker,
)
from app.config import get_settings
from app.main import app
from app.models.enums import ConnectionStatus, StackKind
from app.models.google_connection import GoogleConnection
from app.models.user import User
from app.models.workspace_member import WorkspaceMember
from app.security.token_crypto import load_token_cipher
from app.services.audit_probe import MockAuditProbe
from app.services.connections import upsert_google_connection
from app.services.google_oauth.base import GoogleTokenResponse, GoogleUserInfo
from app.services.stack_detector import StackDetection, StackGuess
from app.services.tls_check import TlsStatus
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


@pytest_asyncio.fixture
def fake_detector():
    """Mock all detection dependencies via FastAPI dependency overrides to avoid real network calls."""

    async def _fake_detect(url: str, *, allow_insecure: bool = False) -> StackDetection:
        _ = (url, allow_insecure)
        return StackDetection(
            StackKind.NEXTJS,
            ("next-static", "next-data"),
            0.85,
            candidates=(StackGuess("Vercel", "en-tetes Vercel"),),
        )

    async def _fake_tls(domain: str) -> TlsStatus:
        _ = domain
        return TlsStatus(
            host=domain,
            status="valid",
            checked_at=datetime.now(UTC),
            expires_at=datetime.now(UTC) + timedelta(days=80),
        )

    async def _fake_gtm(domain: str) -> None:
        _ = domain
        return None

    app.dependency_overrides[get_live_stack_detector] = lambda: _fake_detect
    app.dependency_overrides[get_tls_checker] = lambda: _fake_tls
    app.dependency_overrides[get_gtm_checker] = lambda: _fake_gtm
    app.dependency_overrides[get_audit_probe] = MockAuditProbe
    yield
    app.dependency_overrides.pop(get_live_stack_detector, None)
    app.dependency_overrides.pop(get_tls_checker, None)
    app.dependency_overrides.pop(get_gtm_checker, None)
    app.dependency_overrides.pop(get_audit_probe, None)


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


async def test_summary_exposes_owning_workspace_id(
    authed_client: tuple[AsyncClient, User], db_session: AsyncSession, make_user,
) -> None:
    """La reponse agrege TOUS les workspaces de l'utilisateur : chaque resume
    doit porter son workspace proprietaire pour que le client puisse se
    restreindre au workspace courant."""
    client, user = authed_client
    own_ws = await owner_workspace_id(db_session, user)

    # Second workspace du MEME utilisateur (cree via un autre owner puis
    # l'utilisateur y est ajoute comme membre : `user_workspace_ids` remonte
    # bien les deux, exactement comme pour un utilisateur multi-workspaces).
    other_owner = await make_user(sub="other-owner-ws-scope")
    other_ws = await owner_workspace_id(db_session, other_owner)
    db_session.add(WorkspaceMember(workspace_id=other_ws, user_id=user.id, role="member"))
    await db_session.flush()

    cipher = load_token_cipher(get_settings())
    own_conn = await upsert_google_connection(
        db_session,
        workspace_id=own_ws,
        userinfo=GoogleUserInfo(sub="google-sub-dev-agence", email="dev.agence@gmail.com"),
        token=GoogleTokenResponse(
            access_token="at",
            refresh_token="mock-refresh|google-sub-dev-agence",
            expires_in=3599,
            scopes=_SCOPES,
        ),
        cipher=cipher,
    )
    other_conn = await upsert_google_connection(
        db_session,
        workspace_id=other_ws,
        userinfo=GoogleUserInfo(sub="google-sub-client-perso", email="client.perso@gmail.com"),
        token=GoogleTokenResponse(
            access_token="at",
            refresh_token="mock-refresh|google-sub-client-perso",
            expires_in=3599,
            scopes=_SCOPES,
        ),
        cipher=cipher,
    )

    body = (await client.get("/api/v1/google/resources")).json()
    by_id = {c["id"]: c["workspace_id"] for c in body["connections"]}
    assert by_id[str(own_conn.id)] == str(own_ws)
    assert by_id[str(other_conn.id)] == str(other_ws)


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
    authed_client: tuple[AsyncClient, "User"], db_session: AsyncSession, fake_detector: None,
) -> None:
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
