from urllib.parse import parse_qs, urlparse

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.enums import ConnectionStatus
from app.models.google_connection import GoogleConnection
from app.models.user import User
from app.services.oauth_state import create_oauth_transaction
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
    # URL absolue vers le FRONTEND, jamais un chemin relatif : ce callback
    # est appele sur l'origine du backend, un chemin relatif se resoudrait
    # donc contre elle (404) au lieu du frontend.
    assert resp.headers["location"] == f"{get_settings().frontend_base_url}/connections"

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


async def test_callback_state_is_single_use_even_on_workspace_id_none_error(
    authed_client: tuple[AsyncClient, User], db_session: AsyncSession,
) -> None:
    """Regression : chaque branche d'erreur APRES consume_oauth_state doit committer
    avant de lever, sinon le DELETE flush par consume_oauth_state est annule au
    rollback implicite de fin de requete et le state reste rejouable.

    Ici on force la branche `consumed.workspace_id is None` (transaction issue
    d'un flow de login, jamais d'une connexion de donnees) en creant directement
    une transaction OAuth avec `workspace_id=None`, comme le ferait
    `/auth/google/start`."""
    client, user = authed_client
    transaction = await create_oauth_transaction(
        db_session,
        user_id=user.id,
        workspace_id=None,
        redirect_to="/dashboard",
        ttl_seconds=get_settings().oauth_state_ttl_seconds,
    )
    await db_session.commit()

    resp1 = await client.get(
        "/api/v1/connections/google/callback",
        params={"code": "mock:client_perso", "state": transaction.state},
    )
    assert resp1.status_code == 400
    assert resp1.json()["detail"] == "transaction OAuth invalide pour une connexion de donnees"

    # `db_client` (voir conftest) fait rejouer chaque requete sur le MEME
    # objet `db_session`, jamais ferme entre deux appels HTTP — contrairement
    # a la prod ou `get_session()` fait `async with AsyncSessionLocal() as
    # session: yield session` et ferme (donc rollback les writes flush mais
    # non committes) une session neuve a CHAQUE requete. Sans ce rollback
    # explicite ici, le DELETE flush par `consume_oauth_state` resterait
    # visible "en session" au 2e appel meme si l'endpoint n'avait pas
    # committe — ce qui masquerait totalement la regression testee. On
    # simule donc la fermeture de session par requete pour retrouver le
    # comportement de prod.
    await db_session.rollback()

    # Le state doit avoir ete supprime (usage unique) malgre l'erreur : le
    # rejouer doit maintenant echouer avec le message "state invalide", pas
    # retomber sur la meme erreur "workspace_id manquant".
    resp2 = await client.get(
        "/api/v1/connections/google/callback",
        params={"code": "mock:client_perso", "state": transaction.state},
    )
    assert resp2.status_code == 400
    assert resp2.json()["detail"] == "state OAuth invalide, expire ou deja utilise"
