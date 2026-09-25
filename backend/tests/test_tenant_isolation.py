"""Un utilisateur authentifié d'un workspace ne peut ni lire, ni modifier, ni supprimer
les objets d'un autre workspace, sur AUCUNE route portant un identifiant d'objet."""

from __future__ import annotations

from collections.abc import AsyncGenerator, Callable
from dataclasses import dataclass, fields
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_gtm_headless_verifier
from app.config import get_settings
from app.main import app
from app.models.advisor import AdvisorThread
from app.models.audit_snapshot import AuditSnapshot
from app.models.enums import (
    ConnectionStatus,
    IssueCategory,
    IssueSeverity,
    IssueStatus,
    SnapshotSource,
)
from app.models.google_connection import GoogleConnection
from app.models.issue_item import IssueItem
from app.models.measurement_item_status import MeasurementItemStatus
from app.models.user import User
from app.models.website import Website
from app.models.website_google_link import WebsiteGoogleLink
from app.models.website_profile import WebsiteProfile
from app.models.workspace_invitation import WorkspaceInvitation
from app.models.workspace_member import WorkspaceMember
from app.security.session import issue_session
from app.security.token_crypto import load_token_cipher
from app.services.connections import upsert_google_connection
from app.services.google_oauth.base import GoogleTokenResponse, GoogleUserInfo
from app.services.gtm_headless import GtmHeadlessResult
from tests.conftest import owner_workspace_id

TENANT_PARAMS = ("{website_id}", "{workspace_id}", "{thread_id}", "{issue_id}", "{connection_id}")
VICTIM_DOMAIN = "victime-secrete.test"


@dataclass
class World:
    victim_user_id: UUID
    victim_workspace_id: UUID
    victim_website_id: UUID
    victim_issue_id: UUID
    victim_thread_id: UUID
    victim_connection_id: UUID
    victim_snapshot_id: UUID
    attacker_workspace_id: UUID
    attacker_website_id: UUID
    attacker_connection_id: UUID

    @classmethod
    def random(cls) -> World:
        """Identifiants aléatoires pour chaque champ, sans aucune ligne en base."""
        return cls(**{field.name: uuid4() for field in fields(cls)})

    def path_ids(self) -> dict[str, str]:
        return {
            "website_id": str(self.victim_website_id),
            "workspace_id": str(self.victim_workspace_id),
            "thread_id": str(self.victim_thread_id),
            "issue_id": str(self.victim_issue_id),
            "connection_id": str(self.victim_connection_id),
            "member_user_id": str(self.victim_user_id),
            "item_id": "robots_txt",
        }


Body = dict | Callable[[World], dict] | None

# (méthode, gabarit de route sans /api/v1) -> corps de requête valide, ou None.
CASES: dict[tuple[str, str], Body] = {
    ("GET", "/websites/{website_id}/overview"): None,
    ("GET", "/websites/{website_id}/audit"): None,
    ("GET", "/websites/{website_id}/issues"): None,
    ("GET", "/websites/{website_id}/snippets"): None,
    ("GET", "/websites/{website_id}/ssl"): None,
    ("GET", "/websites/{website_id}/stack-hint"): None,
    ("GET", "/websites/{website_id}/google-links"): None,
    ("GET", "/websites/{website_id}/gtm-export"): None,
    ("GET", "/websites/{website_id}/advisor/threads"): None,
    ("POST", "/websites/{website_id}/scan"): None,
    ("POST", "/websites/{website_id}/gtm/headless"): None,
    ("POST", "/websites/{website_id}/advisor/brief"): None,
    ("POST", "/websites/{website_id}/redetect"): {},
    ("GET", "/websites/{website_id}/measurement-plan"): None,
    ("POST", "/websites/{website_id}/measurement-plan/refresh"): None,
    ("PATCH", "/websites/{website_id}/measurement-plan/profile"): {"uses_google_ads": True},
    ("PATCH", "/websites/{website_id}/measurement-plan/items/{item_id}"): {"dismissed": True},
    ("POST", "/websites/{website_id}/measurement-plan/gtm-container"): {"pack": "starter"},
    ("POST", "/websites/{website_id}/link-resource"): lambda w: {
        "google_connection_id": str(w.attacker_connection_id),
        "resource_type": "ga4_property",
        "resource_id": "properties/1",
    },
    ("PATCH", "/websites/{website_id}/stack"): {"stack_label": "Piraté"},
    ("PATCH", "/websites/{website_id}/issues/{issue_id}"): {"status": "dismissed"},
    ("DELETE", "/websites/{website_id}"): None,
    ("GET", "/advisor/threads/{thread_id}"): None,
    ("DELETE", "/advisor/threads/{thread_id}"): None,
    ("POST", "/advisor/threads/{thread_id}/messages"): {"text": "bonjour"},
    ("DELETE", "/connections/{connection_id}"): None,
    ("POST", "/workspaces/{workspace_id}/invitations"): {"invited_email": "intrus@example.com"},
    ("DELETE", "/workspaces/{workspace_id}/members/{member_user_id}"): None,
}

# Routes portant un identifiant mais volontairement hors de cette suite, avec la raison.
ALLOWLIST: dict[tuple[str, str], str] = {}


async def _connection(
    session: AsyncSession, workspace_id: UUID, sub: str, email: str
) -> GoogleConnection:
    return await upsert_google_connection(
        session,
        workspace_id=workspace_id,
        userinfo=GoogleUserInfo(sub=sub, email=email),
        token=GoogleTokenResponse(
            access_token="access",
            expires_in=3600,
            scopes=("openid",),
            refresh_token=f"refresh-{sub}",
        ),
        cipher=load_token_cipher(get_settings()),
    )


async def _fake_headless_verify(url: str) -> GtmHeadlessResult:
    _ = url
    return GtmHeadlessResult(
        gtm_js_loaded=True,
        containers_initialised=("GTM-CONFIDENTIEL",),
        datalayer_present=True,
        gtm_events=("gtm.js",),
        requests_before_consent=False,
        csp_console_errors=(),
        findings=(),
        checked_at=datetime.now(UTC),
    )


@pytest_asyncio.fixture(autouse=True)
async def _no_real_browser() -> AsyncGenerator[None, None]:
    """Jamais de vrai Chromium : même si le contrôle d'appartenance de la route headless
    disparaissait, elle répondrait 200 (et le test échouerait) au lieu de lancer un
    navigateur."""
    app.dependency_overrides[get_gtm_headless_verifier] = lambda: _fake_headless_verify
    yield
    app.dependency_overrides.pop(get_gtm_headless_verifier, None)


# Instantané de la victime : sans lui, /audit et /gtm/headless répondraient 404
# « aucun audit disponible » même SANS contrôle d'appartenance, et le cas d'isolation
# ne prouverait rien. Avec lui, une route non gardée répond 200 (et renvoie le domaine
# de la victime et « GTM-CONFIDENTIEL »), donc le test échoue.
VICTIM_METRICS = {
    "ga4": {},
    "gsc": {},
    "cwv": {},
    "gtm": {
        "containers": ["GTM-CONFIDENTIEL"],
        "ga4_tags": [],
        "snippet_form": "standard",
        "snippet_in_head": True,
        "data_layer_name": "dataLayer",
        "consent_platform": None,
        "gtm_consent_gated": False,
        "csp_present": False,
        "csp_allows_gtm": None,
        "csp_blocks_preview": None,
        "server_side": False,
        "query_stripped_on_redirect": False,
        "findings": [],
        "checked_at": "2026-09-01T00:00:00+00:00",
        "error": None,
    },
}


@pytest_asyncio.fixture
async def world(
    authed_client: tuple[AsyncClient, User], db_session: AsyncSession, make_user
) -> World:
    _, attacker = authed_client
    attacker_workspace = await owner_workspace_id(db_session, attacker)
    victim = await make_user(sub="victim-sub", email="victim@example.com", name="Victime")
    victim_workspace = await owner_workspace_id(db_session, victim)

    victim_site = Website(
        workspace_id=victim_workspace, domain=VICTIM_DOMAIN, display_name="Victime"
    )
    attacker_site = Website(
        workspace_id=attacker_workspace, domain="attaquant.test", display_name="Attaquant"
    )
    db_session.add_all([victim_site, attacker_site])
    await db_session.flush()

    issue = IssueItem(
        website_id=victim_site.id,
        title="Titre confidentiel",
        description="Description confidentielle",
        category=IssueCategory.SEO,
        severity=IssueSeverity.LOW,
        status=IssueStatus.TODO,
        fingerprint="fp-victim",
        detected_at=datetime.now(UTC),
    )
    thread = AdvisorThread(
        website_id=victim_site.id, persona_key="default", title="Fil confidentiel"
    )
    snapshot = AuditSnapshot(
        website_id=victim_site.id,
        captured_at=datetime.now(UTC),
        source=SnapshotSource.COMPOSITE,
        metrics=VICTIM_METRICS,
    )
    db_session.add_all([issue, thread, snapshot])
    victim_connection = await _connection(
        db_session, victim_workspace, "victim-google", "victime.g@gmail.com"
    )
    attacker_connection = await _connection(
        db_session, attacker_workspace, "attacker-google", "attaquant.g@gmail.com"
    )
    await db_session.flush()

    return World(
        victim_user_id=victim.id,
        victim_workspace_id=victim_workspace,
        victim_website_id=victim_site.id,
        victim_issue_id=issue.id,
        victim_thread_id=thread.id,
        victim_connection_id=victim_connection.id,
        victim_snapshot_id=snapshot.id,
        attacker_workspace_id=attacker_workspace,
        attacker_website_id=attacker_site.id,
        attacker_connection_id=attacker_connection.id,
    )


def _exposed_tenant_routes() -> set[tuple[str, str]]:
    exposed: set[tuple[str, str]] = set()
    for path, operations in app.openapi()["paths"].items():
        if any(param in path for param in TENANT_PARAMS):
            for method in operations:
                exposed.add((method.upper(), path.removeprefix("/api/v1")))
    return exposed


def test_every_tenant_route_has_an_isolation_case() -> None:
    exposed = _exposed_tenant_routes()
    missing = exposed - set(CASES) - set(ALLOWLIST)
    stale = set(CASES) - exposed
    assert not missing, (
        "Routes avec identifiant d'objet sans cas d'isolation : "
        f"{sorted(missing)}. Ajouter chacune à CASES (ou à ALLOWLIST avec la raison)."
    )
    assert not stale, f"CASES référence des routes qui n'existent plus : {sorted(stale)}"


async def test_anonymous_requests_are_rejected_everywhere(db_client: AsyncClient) -> None:
    fake = World.random()
    wrong: list[str] = []
    for (method, template), body in CASES.items():
        payload = body(fake) if callable(body) else body
        resp = await db_client.request(
            method, "/api/v1" + template.format_map(fake.path_ids()), json=payload
        )
        if resp.status_code != 401:
            wrong.append(f"{method} {template} -> {resp.status_code}")
    assert not wrong, wrong


async def test_a_stranger_cannot_reach_or_alter_another_workspace(
    authed_client: tuple[AsyncClient, User], db_session: AsyncSession, world: World
) -> None:
    client, _ = authed_client
    failures: list[str] = []
    for (method, template), body in CASES.items():
        payload = body(world) if callable(body) else body
        path = "/api/v1" + template.format_map(world.path_ids())
        resp = await client.request(method, path, json=payload)
        if resp.status_code not in (403, 404):
            failures.append(f"{method} {template} -> {resp.status_code}")
        if VICTIM_DOMAIN in resp.text or "confidentiel" in resp.text.lower():
            failures.append(f"{method} {template} : la réponse contient des données de la victime")
    assert not failures, "\n".join(failures)

    # Rien n'a bougé chez la victime.
    db_session.expire_all()
    site = await db_session.get(Website, world.victim_website_id)
    assert site is not None and site.stack_label is None and site.archived_at is None
    issue = await db_session.get(IssueItem, world.victim_issue_id)
    assert issue is not None and issue.status == IssueStatus.TODO
    thread = await db_session.get(AdvisorThread, world.victim_thread_id)
    assert thread is not None and thread.archived_at is None
    connection = await db_session.get(GoogleConnection, world.victim_connection_id)
    assert connection is not None and connection.status == ConnectionStatus.ACTIVE
    snapshot = await db_session.get(AuditSnapshot, world.victim_snapshot_id)
    assert snapshot is not None and snapshot.metrics == VICTIM_METRICS
    invitations = await db_session.scalar(
        select(func.count())
        .select_from(WorkspaceInvitation)
        .where(WorkspaceInvitation.workspace_id == world.victim_workspace_id)
    )
    members = await db_session.scalar(
        select(func.count())
        .select_from(WorkspaceMember)
        .where(WorkspaceMember.workspace_id == world.victim_workspace_id)
    )
    links = await db_session.scalar(select(func.count()).select_from(WebsiteGoogleLink))
    assert invitations == 0 and members == 1 and links == 0
    assert await db_session.scalar(select(func.count()).select_from(WebsiteProfile)) == 0
    assert await db_session.scalar(select(func.count()).select_from(MeasurementItemStatus)) == 0


async def test_the_real_owner_reaches_the_seeded_routes(
    authed_client: tuple[AsyncClient, User], world: World
) -> None:
    """Témoin positif : avec les mêmes données, la propriétaire obtient une vraie réponse.
    Le 404 de l'attaquant vient donc du contrôle d'appartenance, pas de données absentes."""
    client, _ = authed_client
    settings = get_settings()
    client.cookies.set(
        settings.session_cookie_name,
        issue_session(world.victim_user_id, secret=settings.app_secret_key.get_secret_value()),
    )
    ids = world.path_ids()

    audit = await client.get(f"/api/v1/websites/{ids['website_id']}/audit")
    assert audit.status_code == 200, audit.text
    assert audit.json()["domain"] == VICTIM_DOMAIN

    headless = await client.post(f"/api/v1/websites/{ids['website_id']}/gtm/headless")
    assert headless.status_code == 200, headless.text
    assert headless.json()["containers_initialised"] == ["GTM-CONFIDENTIEL"]

    issues = await client.get(f"/api/v1/websites/{ids['website_id']}/issues")
    assert issues.status_code == 200
    assert [issue["title"] for issue in issues.json()] == ["Titre confidentiel"]

    thread = await client.get(f"/api/v1/advisor/threads/{ids['thread_id']}")
    assert thread.status_code == 200, thread.text


async def test_cannot_patch_a_victim_issue_through_an_own_website(
    authed_client: tuple[AsyncClient, User], world: World, db_session: AsyncSession
) -> None:
    client, _ = authed_client
    resp = await client.patch(
        f"/api/v1/websites/{world.attacker_website_id}/issues/{world.victim_issue_id}",
        json={"status": "dismissed"},
    )
    assert resp.status_code == 404
    db_session.expire_all()
    issue = await db_session.get(IssueItem, world.victim_issue_id)
    assert issue is not None and issue.status == IssueStatus.TODO


async def test_cannot_link_a_victim_connection_to_an_own_website(
    authed_client: tuple[AsyncClient, User], world: World, db_session: AsyncSession
) -> None:
    client, _ = authed_client
    resp = await client.post(
        f"/api/v1/websites/{world.attacker_website_id}/link-resource",
        json={
            "google_connection_id": str(world.victim_connection_id),
            "resource_type": "ga4_property",
            "resource_id": "properties/1",
        },
    )
    # L'endpoint répond 400 « connexion Google invalide pour cet utilisateur » :
    # refus explicite, ce qui compte est qu'aucune liaison ne soit créée.
    assert resp.status_code in (400, 403, 404)
    assert await db_session.scalar(select(func.count()).select_from(WebsiteGoogleLink)) == 0


async def test_website_list_never_contains_another_workspace(
    authed_client: tuple[AsyncClient, User], world: World
) -> None:
    client, _ = authed_client
    resp = await client.get("/api/v1/websites")
    assert resp.status_code == 200
    domains = {site["domain"] for site in resp.json()}
    assert "attaquant.test" in domains
    assert VICTIM_DOMAIN not in domains
