from urllib.parse import parse_qs, urlparse
from uuid import uuid4

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.models.workspace_member import WorkspaceMember
from tests.conftest import owner_workspace_id


def _query(url: str) -> dict[str, str]:
    return {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}


async def test_start_requires_owner_role(
    authed_client: tuple[AsyncClient, User], db_session: AsyncSession, make_user,
) -> None:
    client, user = authed_client
    other_owner = await make_user(sub="other-owner-conn")
    other_ws = await owner_workspace_id(db_session, other_owner)
    db_session.add(WorkspaceMember(workspace_id=other_ws, user_id=user.id, role="member"))
    await db_session.flush()

    resp = await client.get("/api/v1/connections/google/start", params={"workspace_id": str(other_ws)})
    assert resp.status_code == 403


async def test_start_rejects_non_member_workspace(
    authed_client: tuple[AsyncClient, User],
) -> None:
    client, _ = authed_client
    resp = await client.get("/api/v1/connections/google/start", params={"workspace_id": str(uuid4())})
    assert resp.status_code == 404


async def test_start_owner_gets_data_scopes(
    authed_client: tuple[AsyncClient, User], db_session: AsyncSession,
) -> None:
    client, user = authed_client
    ws_id = await owner_workspace_id(db_session, user)
    resp = await client.get("/api/v1/connections/google/start", params={"workspace_id": str(ws_id)})
    assert resp.status_code == 200
    params = _query(resp.json()["authorization_url"])
    scopes = params["scope"].split()
    assert "https://www.googleapis.com/auth/analytics.readonly" in scopes
    assert "https://www.googleapis.com/auth/webmasters.readonly" in scopes
    assert not any("tagmanager" in s for s in scopes)


async def test_login_and_data_flows_use_distinct_redirect_uris(
    authed_client: tuple[AsyncClient, User], db_session: AsyncSession,
) -> None:
    """Regression : les deux flows partagent le meme client OAuth. Tant que
    `/connections/google/start` n'imposait pas son propre redirect_uri, le
    consentement de donnees revenait sur le callback de LOGIN — l'utilisateur
    etait silencieusement reconnecte et aucune connexion n'etait creee."""
    client, user = authed_client
    ws_id = await owner_workspace_id(db_session, user)

    login = await client.get("/api/v1/auth/google/start")
    assert login.status_code == 200, login.text
    login_redirect = _query(login.json()["authorization_url"])["redirect_uri"]

    data = await client.get(
        "/api/v1/connections/google/start", params={"workspace_id": str(ws_id)}
    )
    assert data.status_code == 200, data.text
    data_redirect = _query(data.json()["authorization_url"])["redirect_uri"]

    assert login_redirect.endswith("/auth/google/callback")
    assert data_redirect.endswith("/connections/google/callback")
    assert login_redirect != data_redirect


async def test_start_requires_authentication(db_client: AsyncClient) -> None:
    resp = await db_client.get("/api/v1/connections/google/start", params={"workspace_id": str(uuid4())})
    assert resp.status_code == 401
