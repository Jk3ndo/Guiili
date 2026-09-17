"""POST/GET /websites : creation, normalisation, stack, SSL, archivage."""

from datetime import UTC, datetime, timedelta

import pytest
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
from app.api.v1.endpoints.websites import normalize_domain
from app.config import get_settings
from app.main import app
from app.models.audit_snapshot import AuditSnapshot
from app.models.enums import StackKind
from app.models.issue_item import IssueItem
from app.models.user import User
from app.models.website import Website
from app.models.workspace import Workspace
from app.models.workspace_member import WorkspaceMember
from app.security.session import issue_session
from app.services.audit_probe import MockAuditProbe
from app.services.stack_detector import StackDetection, StackGuess
from app.services.tls_check import TlsStatus
from tests.conftest import owner_workspace_id


@pytest_asyncio.fixture
def fake_detector():
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

    # Independant de AUDIT_PROBE_MOCK dans .env : la suite reste deterministe
    # meme quand le dev bascule son environnement local en mode reel.
    app.dependency_overrides[get_live_stack_detector] = lambda: _fake
    app.dependency_overrides[get_tls_checker] = lambda: _fake_tls
    app.dependency_overrides[get_gtm_checker] = lambda: _fake_gtm
    app.dependency_overrides[get_audit_probe] = MockAuditProbe
    yield
    app.dependency_overrides.pop(get_live_stack_detector, None)
    app.dependency_overrides.pop(get_tls_checker, None)
    app.dependency_overrides.pop(get_gtm_checker, None)
    app.dependency_overrides.pop(get_audit_probe, None)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("https://mon-site.fr/", "mon-site.fr"),
        ("  HTTP://WWW.Mon-Site.FR  ", "mon-site.fr"),
        ("mon-site.fr/blog?utm=x#top", "mon-site.fr"),
        ("http://user@shop.example.co.uk:8443/path", "shop.example.co.uk"),
        ("www.example.com.", "example.com"),
    ],
)
def test_normalize_domain(raw: str, expected: str) -> None:
    assert normalize_domain(raw) == expected


async def test_create_runs_first_audit_and_returns_snapshot(
    authed_client: tuple[AsyncClient, User],
    db_session: AsyncSession,
    fake_detector: None,
) -> None:
    client, user = authed_client

    resp = await client.post(
        "/api/v1/websites",
        json={"name": "  Mon E-commerce  ", "domain": "https://Nouveau-Site.fr/boutique"},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()

    assert body["domain"] == "nouveau-site.fr"
    assert body["display_name"] == "Mon E-commerce"
    assert body["detected_stack"] == "nextjs"
    assert body["detection"]["stack"] == "nextjs"
    assert "next-static" in body["detection"]["signals"]
    assert body["detection"]["candidates"][0]["label"] == "Vercel"
    assert body["ssl"]["status"] == "valid"
    assert body["captured_at"] is not None
    assert body["workspace_id"] == str(await owner_workspace_id(db_session, user))

    site = (await db_session.execute(select(Website).where(Website.id == body["id"]))).scalar_one()
    assert site.workspace_id == await owner_workspace_id(db_session, user)
    assert site.detected_stack is StackKind.NEXTJS
    assert site.ssl_status == "valid"
    assert site.ssl_checked_at is not None

    snap = (
        await db_session.execute(
            select(AuditSnapshot).where(AuditSnapshot.id == body["snapshot_id"])
        )
    ).scalar_one()
    assert snap.website_id == site.id


async def test_list_websites_exposes_workspace_id(
    authed_client: tuple[AsyncClient, User],
    db_session: AsyncSession,
    fake_detector: None,
) -> None:
    client, user = authed_client
    await client.post("/api/v1/websites", json={"name": "X", "domain": "expose-wsid.test"})
    resp = await client.get("/api/v1/websites")
    body = next(w for w in resp.json() if w["domain"] == "expose-wsid.test")
    assert body["workspace_id"] == str(await owner_workspace_id(db_session, user))


async def test_create_rejects_duplicate_domain_for_same_user(
    authed_client: tuple[AsyncClient, User],
    fake_detector: None,
) -> None:
    client, _user = authed_client
    first = await client.post("/api/v1/websites", json={"name": "A", "domain": "dup.example"})
    assert first.status_code == 201
    again = await client.post(
        "/api/v1/websites", json={"name": "A bis", "domain": "https://dup.example/"}
    )
    assert again.status_code == 409


async def test_create_lands_in_owned_workspace_not_joined_one(
    db_client: AsyncClient,
    db_session: AsyncSession,
    make_user,
    fake_detector: None,
) -> None:
    """Un utilisateur membre (invite) d'un workspace ET owner d'un autre doit
    voir son nouveau site atterrir dans le workspace qu'il possede, jamais
    dans celui ou il n'est que membre invite — regression sur le tri
    deterministe (role owner en priorite) de la resolution get-or-create.

    On n'utilise volontairement PAS `authed_client` : sa fixture cree la
    ligne WorkspaceMember "owner" de l'utilisateur AVANT tout, si bien que
    l'ordre de retour naturel (non trie) de Postgres pour ce petit jeu de
    lignes fraichement inserees dans une seule transaction correspond deja
    a l'ordre d'insertion — et fait passer le test meme sans le `order_by`
    du fix (constate empiriquement : revert du `order_by`, test toujours
    vert). Ici on inverse deliberement l'ordre d'insertion des deux lignes
    WorkspaceMember de l'utilisateur (le role "member" ecrit AVANT le role
    "owner"), pour que `.first()` sans tri choisisse le mauvais workspace
    si le `order_by` par role est absent, et exerce donc reellement le fix."""
    other_owner = await make_user(sub="other-owner-ws-2")
    other_ws = await owner_workspace_id(db_session, other_owner)

    user = User(email="invited-then-owner@example.com", google_sub="invited-then-owner")
    db_session.add(user)
    await db_session.flush()

    # 1) ligne "membre invite" ecrite EN PREMIER pour cet utilisateur.
    db_session.add(WorkspaceMember(workspace_id=other_ws, user_id=user.id, role="member"))
    await db_session.flush()

    # 2) son propre workspace (owner) ecrit EN SECOND.
    own_ws_row = Workspace(name="Mine", owner_user_id=user.id)
    db_session.add(own_ws_row)
    await db_session.flush()
    db_session.add(WorkspaceMember(workspace_id=own_ws_row.id, user_id=user.id, role="owner"))
    await db_session.flush()
    own_ws = own_ws_row.id

    settings = get_settings()
    db_client.cookies.set(
        settings.session_cookie_name,
        issue_session(user.id, secret=settings.app_secret_key.get_secret_value()),
    )

    resp = await db_client.post(
        "/api/v1/websites", json={"name": "Nouveau", "domain": "nouveau-membre.test"}
    )
    assert resp.status_code == 201, resp.text

    site = (
        await db_session.execute(
            select(Website).where(Website.domain == "nouveau-membre.test")
        )
    ).scalar_one()
    assert site.workspace_id == own_ws
    assert site.workspace_id != other_ws


async def test_same_domain_allowed_for_a_different_user(
    authed_client: tuple[AsyncClient, User],
    db_session: AsyncSession,
    make_user,
    fake_detector: None,
) -> None:
    client, _user = authed_client
    assert (
        await client.post("/api/v1/websites", json={"name": "Mine", "domain": "shared.example"})
    ).status_code == 201

    stranger = await make_user(sub="stranger-web", email="stranger@example.com")
    stranger_workspace_id = await owner_workspace_id(db_session, stranger)
    site = Website(workspace_id=stranger_workspace_id, domain="shared.example", display_name="Theirs")
    db_session.add(site)
    await db_session.flush()  # pas d'IntegrityError : unicite (workspace_id, domain)

    listed = (await client.get("/api/v1/websites")).json()
    assert [w["domain"] for w in listed] == ["shared.example"]  # isole a l'utilisateur


@pytest.mark.parametrize("bad", ["", "   ", "not a domain", "http://", "localhost", "a..b"])
async def test_create_rejects_invalid_domain(
    authed_client: tuple[AsyncClient, User],
    fake_detector: None,
    bad: str,
) -> None:
    client, _user = authed_client
    resp = await client.post("/api/v1/websites", json={"name": "X", "domain": bad})
    assert resp.status_code == 422


async def _create(client: AsyncClient, domain: str, name: str = "Site") -> dict:
    resp = await client.post("/api/v1/websites", json={"name": name, "domain": domain})
    assert resp.status_code == 201, resp.text
    return resp.json()


async def test_set_stack_label_overrides_detection(
    authed_client: tuple[AsyncClient, User], db_session: AsyncSession, fake_detector: None
) -> None:
    client, _user = authed_client
    site_id = (await _create(client, "libre.example"))["id"]

    resp = await client.patch(
        f"/api/v1/websites/{site_id}/stack", json={"stack_label": "  Symfony 7 (maison)  "}
    )
    assert resp.status_code == 200
    assert resp.json()["stack_label"] == "Symfony 7 (maison)"
    assert resp.json()["detected_stack"] == "nextjs"  # la detection auto reste

    site = await db_session.get(Website, site_id)
    await db_session.refresh(site)
    assert site.stack_label == "Symfony 7 (maison)"

    bad = await client.patch(f"/api/v1/websites/{site_id}/stack", json={"stack_label": "   "})
    assert bad.status_code == 422


async def test_stack_hint_from_last_snapshot(
    authed_client: tuple[AsyncClient, User], fake_detector: None
) -> None:
    client, _user = authed_client
    site_id = (await _create(client, "hint.example"))["id"]

    hint = (await client.get(f"/api/v1/websites/{site_id}/stack-hint")).json()
    assert hint["detected_stack"] == "nextjs"
    assert hint["needs_confirmation"] is False  # nextjs, confiance 0.85

    await client.patch(f"/api/v1/websites/{site_id}/stack", json={"stack_label": "Astro"})
    hint2 = (await client.get(f"/api/v1/websites/{site_id}/stack-hint")).json()
    assert hint2["stack_label"] == "Astro"
    assert hint2["needs_confirmation"] is False


async def test_redetect_updates_stack(
    authed_client: tuple[AsyncClient, User], fake_detector: None
) -> None:
    client, _user = authed_client
    site_id = (await _create(client, "redetect.example"))["id"]
    resp = await client.post(f"/api/v1/websites/{site_id}/redetect", json={"allow_insecure": True})
    assert resp.status_code == 200
    assert resp.json()["detected_stack"] == "nextjs"
    assert resp.json()["detection"]["candidates"][0]["label"] == "Vercel"


async def test_ssl_endpoint_refreshes_status(
    authed_client: tuple[AsyncClient, User], db_session: AsyncSession, fake_detector: None
) -> None:
    client, _user = authed_client
    site_id = (await _create(client, "ssl.example"))["id"]

    resp = await client.get(f"/api/v1/websites/{site_id}/ssl")
    assert resp.status_code == 200
    assert resp.json()["status"] == "valid"
    assert resp.json()["expires_at"] is not None

    site = await db_session.get(Website, site_id)
    await db_session.refresh(site)
    assert site.ssl_status == "valid"


async def test_archive_hides_site_and_purge_deletes_it(
    authed_client: tuple[AsyncClient, User], db_session: AsyncSession, fake_detector: None
) -> None:
    client, _user = authed_client
    keep = (await _create(client, "keep.example", "Keep"))["id"]
    gone = await _create(client, "gone.example", "Gone")
    gone_id, snap_id = gone["id"], gone["snapshot_id"]

    # archivage doux : exclu de la liste, toujours en base
    assert (await client.delete(f"/api/v1/websites/{gone_id}")).status_code == 204
    domains = {w["domain"] for w in (await client.get("/api/v1/websites")).json()}
    assert domains == {"keep.example"}
    assert (await client.get("/api/v1/websites?include_archived=true")).json().__len__() == 2
    assert await db_session.get(Website, gone_id) is not None

    # purge : suppression definitive en cascade (snapshot + issues)
    assert (await client.delete(f"/api/v1/websites/{gone_id}?purge=true")).status_code == 204
    await db_session.commit()
    assert await db_session.get(Website, gone_id) is None
    assert await db_session.get(AuditSnapshot, snap_id) is None
    orphans = (
        (await db_session.execute(select(IssueItem).where(IssueItem.website_id == gone_id)))
        .scalars()
        .all()
    )
    assert orphans == []
    _ = keep


async def test_allow_insecure_persisted_on_creation(
    authed_client: tuple[AsyncClient, User], db_session: AsyncSession, fake_detector: None
) -> None:
    client, _user = authed_client
    body = await client.post(
        "/api/v1/websites",
        json={"name": "Insecure", "domain": "expired-cert.example", "allow_insecure": True},
    )
    assert body.status_code == 201
    site = await db_session.get(Website, body.json()["id"])
    await db_session.refresh(site)
    assert site.allow_insecure_probe is True


async def test_list_websites_includes_sites_from_joined_workspace(
    authed_client: tuple[AsyncClient, User],
    db_session: AsyncSession,
    make_user,
) -> None:
    client, user = authed_client
    own_ws = await owner_workspace_id(db_session, user)
    db_session.add(Website(workspace_id=own_ws, domain="mine.test", display_name="Mine"))

    other_owner = await make_user(sub="other-owner-ws")
    other_ws = await owner_workspace_id(db_session, other_owner)
    db_session.add(Website(workspace_id=other_ws, domain="shared.test", display_name="Shared"))
    db_session.add(WorkspaceMember(workspace_id=other_ws, user_id=user.id, role="member"))
    await db_session.flush()

    resp = await client.get("/api/v1/websites")
    domains = {w["domain"] for w in resp.json()}
    assert domains == {"mine.test", "shared.test"}


async def test_endpoints_require_auth(db_client: AsyncClient) -> None:
    fake = "00000000-0000-0000-0000-000000000000"
    assert (await db_client.get("/api/v1/websites")).status_code == 401
    assert (
        await db_client.post("/api/v1/websites", json={"name": "X", "domain": "x.fr"})
    ).status_code == 401
    assert (await db_client.get(f"/api/v1/websites/{fake}/ssl")).status_code == 401
    assert (await db_client.delete(f"/api/v1/websites/{fake}")).status_code == 401
    assert (
        await db_client.patch(f"/api/v1/websites/{fake}/stack", json={"stack_label": "x"})
    ).status_code == 401
