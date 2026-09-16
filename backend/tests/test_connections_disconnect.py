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
from app.models.website_google_link import WebsiteGoogleLink
from app.models.workspace_member import WorkspaceMember
from app.security.session import issue_session
from app.services.audit_probe import MockAuditProbe
from app.services.stack_detector import StackDetection, StackGuess
from app.services.tls_check import TlsStatus
from tests.conftest import owner_workspace_id


def _query(url: str) -> dict[str, str]:
    return {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}


@pytest_asyncio.fixture
def fake_detector():
    """Reprend a l'identique le fixture de test_websites.py (non partage via
    conftest.py) : POST /websites y fait appel pour la creation de site dans
    test_disconnect_marks_revoked_and_keeps_links, et doit rester independant
    de tout appel reseau reel ou de AUDIT_PROBE_MOCK dans .env."""

    async def _fake(url: str, *, allow_insecure: bool = False) -> StackDetection:
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

    app.dependency_overrides[get_live_stack_detector] = lambda: _fake
    app.dependency_overrides[get_tls_checker] = lambda: _fake_tls
    app.dependency_overrides[get_gtm_checker] = lambda: _fake_gtm
    app.dependency_overrides[get_audit_probe] = MockAuditProbe
    yield
    app.dependency_overrides.pop(get_live_stack_detector, None)
    app.dependency_overrides.pop(get_tls_checker, None)
    app.dependency_overrides.pop(get_gtm_checker, None)
    app.dependency_overrides.pop(get_audit_probe, None)


async def _connect(client: AsyncClient, workspace_id) -> None:
    start = await client.get(
        "/api/v1/connections/google/start", params={"workspace_id": str(workspace_id)}
    )
    state = _query(start.json()["authorization_url"])["state"]
    await client.get(
        "/api/v1/connections/google/callback",
        params={"code": "mock:client_perso", "state": state},
        follow_redirects=False,
    )


def _login_as(client: AsyncClient, user: User) -> None:
    """Reassigne le cookie de session du client a un autre utilisateur, pour
    simuler un second appelant authentifie sans instancier un second client."""
    settings = get_settings()
    client.cookies.set(
        settings.session_cookie_name,
        issue_session(user.id, secret=settings.app_secret_key.get_secret_value()),
    )


async def test_disconnect_owner_can_disconnect(
    authed_client: tuple[AsyncClient, User], db_session: AsyncSession, make_user,
) -> None:
    """Sanity check positif : le proprietaire peut se deconnecter lui-meme.

    Ne verifie PAS le rejet d'un non-proprietaire — voir
    test_disconnect_rejects_non_owner ci-dessous pour ce cas.
    """
    client, user = authed_client
    ws_id = await owner_workspace_id(db_session, user)
    await _connect(client, ws_id)
    conn = (
        await db_session.execute(select(GoogleConnection).where(GoogleConnection.workspace_id == ws_id))
    ).scalar_one()

    other_owner = await make_user(sub="other-owner-disc")
    other_ws = await owner_workspace_id(db_session, other_owner)
    db_session.add(WorkspaceMember(workspace_id=ws_id, user_id=other_owner.id, role="member"))
    await db_session.flush()

    resp = await client.delete(f"/api/v1/connections/{conn.id}")
    assert resp.status_code == 200  # l'appelant EST le proprietaire ici : sanity check positif
    _ = other_ws  # utilise seulement pour construire un membre non-owner distinct


async def test_disconnect_rejects_non_owner(
    authed_client: tuple[AsyncClient, User], db_session: AsyncSession, make_user,
) -> None:
    """Un membre non-proprietaire du workspace ne peut pas deconnecter la
    connexion Google de ce workspace (403), meme s'il est bien membre."""
    client, user = authed_client
    other_owner = await make_user(sub="other-owner-disc-reject")
    other_ws = await owner_workspace_id(db_session, other_owner)

    # other_owner est proprietaire de other_ws : il peut initier la connexion.
    _login_as(client, other_owner)
    await _connect(client, other_ws)
    conn = (
        await db_session.execute(
            select(GoogleConnection).where(GoogleConnection.workspace_id == other_ws)
        )
    ).scalar_one()

    # `user` (l'appelant original) devient simple membre de other_ws, pas owner.
    db_session.add(WorkspaceMember(workspace_id=other_ws, user_id=user.id, role="member"))
    await db_session.flush()

    # On rebascule sur la session de `user` pour tenter la deconnexion.
    _login_as(client, user)
    resp = await client.delete(f"/api/v1/connections/{conn.id}")
    assert resp.status_code == 403


async def test_disconnect_marks_revoked_and_keeps_links(
    authed_client: tuple[AsyncClient, User], db_session: AsyncSession, fake_detector: None,
) -> None:
    client, user = authed_client
    ws_id = await owner_workspace_id(db_session, user)
    await _connect(client, ws_id)
    conn = (
        await db_session.execute(select(GoogleConnection).where(GoogleConnection.workspace_id == ws_id))
    ).scalar_one()

    site_resp = await client.post("/api/v1/websites", json={"name": "S", "domain": "disc-test.example"})
    site_id = site_resp.json()["id"]
    db_session.add(
        WebsiteGoogleLink(
            website_id=site_id, google_connection_id=conn.id,
            resource_type="ga4_property", resource_id="properties/1",
        )
    )
    await db_session.flush()

    resp = await client.delete(f"/api/v1/connections/{conn.id}")
    assert resp.status_code == 200
    assert resp.json()["status"] == "revoked"

    await db_session.refresh(conn)
    assert conn.status == ConnectionStatus.REVOKED

    links = (
        await db_session.execute(select(WebsiteGoogleLink).where(WebsiteGoogleLink.website_id == site_id))
    ).scalars().all()
    assert len(links) == 1  # jamais supprimee


async def test_disconnect_not_found(authed_client: tuple[AsyncClient, User]) -> None:
    client, _ = authed_client
    resp = await client.delete(f"/api/v1/connections/{uuid4()}")
    assert resp.status_code == 404
