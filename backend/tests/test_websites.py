"""POST/GET /websites : creation + premier diagnostic + normalisation + isolation."""

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_live_stack_detector
from app.api.v1.endpoints.websites import normalize_domain
from app.main import app
from app.models.audit_snapshot import AuditSnapshot
from app.models.enums import StackKind
from app.models.user import User
from app.models.website import Website
from app.services.stack_detector import StackDetection


@pytest_asyncio.fixture
def fake_detector():
    async def _fake(url: str) -> StackDetection:
        _ = url
        return StackDetection(StackKind.NEXTJS, ("next-static", "next-data"), 0.85)

    app.dependency_overrides[get_live_stack_detector] = lambda: _fake
    yield
    app.dependency_overrides.pop(get_live_stack_detector, None)


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
    assert body["captured_at"] is not None

    site = (await db_session.execute(select(Website).where(Website.id == body["id"]))).scalar_one()
    assert site.user_id == user.id
    assert site.detected_stack is StackKind.NEXTJS

    snap = (
        await db_session.execute(
            select(AuditSnapshot).where(AuditSnapshot.id == body["snapshot_id"])
        )
    ).scalar_one()
    assert snap.website_id == site.id


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
    site = Website(user_id=stranger.id, domain="shared.example", display_name="Theirs")
    db_session.add(site)
    await db_session.flush()  # pas d'IntegrityError : unicite (user_id, domain)

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


async def test_endpoints_require_auth(db_client: AsyncClient) -> None:
    assert (await db_client.get("/api/v1/websites")).status_code == 401
    assert (
        await db_client.post("/api/v1/websites", json={"name": "X", "domain": "x.fr"})
    ).status_code == 401
