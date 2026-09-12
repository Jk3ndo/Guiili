"""Login Google en scopes identite seule : pas de connexion de donnees creee,
garde-fou contre la fusion silencieuse avec un compte mot de passe existant."""

from urllib.parse import parse_qs, urlparse

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.google_connection import GoogleConnection
from app.models.user import User
from app.models.workspace_member import WorkspaceMember


def _query(url: str) -> dict[str, str]:
    return {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}


async def _start(client: AsyncClient) -> str:
    resp = await client.get("/api/v1/auth/google/start")
    assert resp.status_code == 200, resp.text
    return _query(resp.json()["authorization_url"])["state"]


async def test_google_login_does_not_create_google_connection(
    db_client: AsyncClient, db_session: AsyncSession
) -> None:
    state = await _start(db_client)
    resp = await db_client.get(
        "/api/v1/auth/google/callback",
        params={"code": "mock:client_perso", "state": state},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    conns = (await db_session.execute(select(GoogleConnection))).scalars().all()
    assert conns == []


async def test_google_login_new_user_gets_own_workspace(
    db_client: AsyncClient, db_session: AsyncSession
) -> None:
    state = await _start(db_client)
    resp = await db_client.get(
        "/api/v1/auth/google/callback",
        params={"code": "mock:dev_agence", "state": state},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert "cc_session" in resp.cookies

    user = (
        await db_session.execute(select(User).where(User.google_sub == "google-sub-dev-agence"))
    ).scalar_one()
    membership = (
        await db_session.execute(select(WorkspaceMember).where(WorkspaceMember.user_id == user.id))
    ).scalar_one()
    assert membership.role == "owner"


async def test_google_login_rejects_email_already_password_based(
    db_client: AsyncClient,
) -> None:
    await db_client.post(
        "/api/v1/auth/register",
        json={
            "email": "client.perso@gmail.com",  # meme email que la fixture mock "client_perso"
            "password": "correct horse battery staple",
            "display_name": "Deja inscrit",
        },
    )
    db_client.cookies.clear()
    state = await _start(db_client)
    resp = await db_client.get(
        "/api/v1/auth/google/callback",
        params={"code": "mock:client_perso", "state": state},
        follow_redirects=False,
    )
    assert resp.status_code == 400
    assert "mot de passe" in resp.json()["detail"].lower()
