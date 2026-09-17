"""Flux OAuth complet en mode mock : start (PKCE + state) -> callback."""

from urllib.parse import parse_qs, urlparse

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.oauth_state import OAuthState
from app.models.user import User
from app.services.oauth_state import create_oauth_transaction
from tests.conftest import owner_workspace_id


def _query(url: str) -> dict[str, str]:
    return {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}


async def _start(client: AsyncClient) -> str:
    resp = await client.get("/api/v1/auth/google/start")
    assert resp.status_code == 200, resp.text
    return _query(resp.json()["authorization_url"])["state"]


async def test_start_generates_pkce_challenge_and_persists_state(
    db_client: AsyncClient, db_session: AsyncSession
) -> None:
    resp = await db_client.get("/api/v1/auth/google/start")
    assert resp.status_code == 200
    params = _query(resp.json()["authorization_url"])
    assert params["code_challenge_method"] == "S256"
    assert len(params["code_challenge"]) >= 43
    assert "state" in params

    row = (
        await db_session.execute(select(OAuthState).where(OAuthState.state == params["state"]))
    ).scalar_one()
    assert row.user_id is None
    assert 20 <= len(row.code_verifier) <= 128


async def test_callback_logs_in_creates_user(
    db_client: AsyncClient, db_session: AsyncSession
) -> None:
    state = await _start(db_client)
    resp = await db_client.get(
        "/api/v1/auth/google/callback",
        params={"code": "mock:client_perso", "state": state},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert resp.headers["location"] == get_settings().frontend_base_url
    assert "cc_session" in resp.cookies

    user = (
        await db_session.execute(select(User).where(User.google_sub == "google-sub-client-perso"))
    ).scalar_one()
    assert user.email == "client.perso@gmail.com"


async def test_state_is_single_use(db_client: AsyncClient) -> None:
    state = await _start(db_client)
    first = await db_client.get(
        "/api/v1/auth/google/callback",
        params={"code": "mock:dev_agence", "state": state},
        follow_redirects=False,
    )
    assert first.status_code == 302
    second = await db_client.get(
        "/api/v1/auth/google/callback",
        params={"code": "mock:dev_agence", "state": state},
        follow_redirects=False,
    )
    assert second.status_code == 400


async def test_callback_rejects_unknown_state(db_client: AsyncClient) -> None:
    resp = await db_client.get(
        "/api/v1/auth/google/callback",
        params={"code": "mock:dev_agence", "state": "forged-state"},
        follow_redirects=False,
    )
    assert resp.status_code == 400


async def test_callback_rejects_data_connection_state(
    authed_client: tuple[AsyncClient, User], db_session: AsyncSession,
) -> None:
    """Symetrique de test_connections_google_callback.py::
    test_callback_state_is_single_use_even_on_workspace_id_none_error : une
    transaction portant un `workspace_id` vient du flow de connexion de
    DONNEES et ne doit jamais etre traitee comme un login (sinon l'utilisateur
    serait silencieusement reconnecte au lieu de voir sa connexion creee)."""
    client, user = authed_client
    ws_id = await owner_workspace_id(db_session, user)
    transaction = await create_oauth_transaction(
        db_session,
        user_id=user.id,
        workspace_id=ws_id,
        redirect_to="/connections",
        ttl_seconds=get_settings().oauth_state_ttl_seconds,
    )
    await db_session.commit()

    resp = await client.get(
        "/api/v1/auth/google/callback",
        params={"code": "mock:client_perso", "state": transaction.state},
        follow_redirects=False,
    )
    assert resp.status_code == 400
    assert resp.json()["detail"] == "transaction OAuth invalide pour un login"


async def test_callback_rejects_denied_consent(db_client: AsyncClient) -> None:
    resp = await db_client.get(
        "/api/v1/auth/google/callback",
        params={"error": "access_denied", "state": "x"},
        follow_redirects=False,
    )
    assert resp.status_code == 400
