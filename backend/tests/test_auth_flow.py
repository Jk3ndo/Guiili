"""Flux OAuth complet en mode mock : start (PKCE + state) -> callback."""

from urllib.parse import parse_qs, urlparse

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import ConnectionStatus
from app.models.google_connection import GoogleConnection
from app.models.oauth_state import OAuthState
from app.models.user import User


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


async def test_callback_logs_in_creates_user_and_encrypted_connection(
    db_client: AsyncClient, db_session: AsyncSession
) -> None:
    state = await _start(db_client)
    resp = await db_client.get(
        "/api/v1/auth/google/callback",
        params={"code": "mock:client_perso", "state": state},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert resp.headers["location"] == "http://localhost:4000"
    assert "cc_session" in resp.cookies

    user = (
        await db_session.execute(select(User).where(User.google_sub == "google-sub-client-perso"))
    ).scalar_one()
    assert user.email == "client.perso@gmail.com"

    conn = (
        await db_session.execute(
            select(GoogleConnection).where(GoogleConnection.user_id == user.id)
        )
    ).scalar_one()
    assert conn.status == ConnectionStatus.ACTIVE
    assert conn.google_sub == "google-sub-client-perso"
    # le refresh token n'est jamais stocke en clair
    assert b"mock-refresh" not in conn.refresh_token_encrypted
    assert conn.encryption_key_version == 1
    assert set(conn.granted_scopes) >= {"openid", "email"}


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


async def test_callback_rejects_denied_consent(db_client: AsyncClient) -> None:
    resp = await db_client.get(
        "/api/v1/auth/google/callback",
        params={"error": "access_denied", "state": "x"},
        follow_redirects=False,
    )
    assert resp.status_code == 400


async def test_reauth_updates_connection_without_duplicate(
    db_client: AsyncClient, db_session: AsyncSession
) -> None:
    for _ in range(2):
        state = await _start(db_client)
        resp = await db_client.get(
            "/api/v1/auth/google/callback",
            params={"code": "mock:dev_agence", "state": state},
            follow_redirects=False,
        )
        assert resp.status_code == 302

    conns = (await db_session.execute(select(GoogleConnection))).scalars().all()
    assert len(conns) == 1


async def test_logged_in_user_adds_second_account(
    authed_client: tuple[AsyncClient, User], db_session: AsyncSession
) -> None:
    client, user = authed_client
    # l'user est deja loggé -> le start lie le state a son id
    state = await _start(client)
    row = (
        await db_session.execute(select(OAuthState).where(OAuthState.state == state))
    ).scalar_one()
    assert row.user_id == user.id

    resp = await client.get(
        "/api/v1/auth/google/callback",
        params={"code": "mock:dev_agence", "state": state},
        follow_redirects=False,
    )
    assert resp.status_code == 302

    conns = (
        (
            await db_session.execute(
                select(GoogleConnection).where(GoogleConnection.user_id == user.id)
            )
        )
        .scalars()
        .all()
    )
    # la connexion est rattachee a l'utilisateur de session, pas a un nouvel user
    assert len(conns) == 1
    assert conns[0].google_sub == "google-sub-dev-agence"
    users = (await db_session.execute(select(User))).scalars().all()
    assert len(users) == 1
