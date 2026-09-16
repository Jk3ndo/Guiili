from urllib.parse import parse_qs, urlparse

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import ConnectionStatus
from app.models.google_connection import GoogleConnection
from app.models.user import User
from tests.conftest import owner_workspace_id


def _query(url: str) -> dict[str, str]:
    return {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}


async def _start(client: AsyncClient, workspace_id) -> str:
    resp = await client.get(
        "/api/v1/connections/google/start", params={"workspace_id": str(workspace_id)}
    )
    assert resp.status_code == 200, resp.text
    return _query(resp.json()["authorization_url"])["state"]


async def test_callback_creates_connection(
    authed_client: tuple[AsyncClient, User], db_session: AsyncSession,
) -> None:
    client, user = authed_client
    ws_id = await owner_workspace_id(db_session, user)
    state = await _start(client, ws_id)

    resp = await client.get(
        "/api/v1/connections/google/callback",
        params={"code": "mock:client_perso", "state": state},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert resp.headers["location"].endswith("/connections")

    conn = (
        await db_session.execute(
            select(GoogleConnection).where(GoogleConnection.workspace_id == ws_id)
        )
    ).scalar_one()
    assert conn.google_account_email == "client.perso@gmail.com"
    assert conn.status == ConnectionStatus.ACTIVE


async def test_callback_reconnect_reactivates_revoked_connection(
    authed_client: tuple[AsyncClient, User], db_session: AsyncSession,
) -> None:
    client, user = authed_client
    ws_id = await owner_workspace_id(db_session, user)

    state1 = await _start(client, ws_id)
    await client.get(
        "/api/v1/connections/google/callback",
        params={"code": "mock:client_perso", "state": state1},
        follow_redirects=False,
    )
    conn = (
        await db_session.execute(
            select(GoogleConnection).where(GoogleConnection.workspace_id == ws_id)
        )
    ).scalar_one()
    conn.status = ConnectionStatus.REVOKED
    await db_session.commit()

    state2 = await _start(client, ws_id)
    resp2 = await client.get(
        "/api/v1/connections/google/callback",
        params={"code": "mock:client_perso", "state": state2},
        follow_redirects=False,
    )
    assert resp2.status_code == 302

    conns = (
        await db_session.execute(
            select(GoogleConnection).where(GoogleConnection.workspace_id == ws_id)
        )
    ).scalars().all()
    assert len(conns) == 1  # pas de doublon
    assert conns[0].status == ConnectionStatus.ACTIVE  # reactivee


async def test_callback_rejects_denied_consent(
    authed_client: tuple[AsyncClient, User], db_session: AsyncSession,
) -> None:
    client, user = authed_client
    ws_id = await owner_workspace_id(db_session, user)
    await _start(client, ws_id)  # cree une transaction (state non utilise ici)
    resp = await client.get(
        "/api/v1/connections/google/callback",
        params={"error": "access_denied", "state": "peu-importe"},
    )
    assert resp.status_code == 400


async def test_callback_rejects_invalid_state(authed_client: tuple[AsyncClient, User]) -> None:
    client, _ = authed_client
    resp = await client.get(
        "/api/v1/connections/google/callback",
        params={"code": "mock:client_perso", "state": "invalide"},
    )
    assert resp.status_code == 400
