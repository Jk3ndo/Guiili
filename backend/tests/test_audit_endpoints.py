"""Endpoints d'audit : scan, overview, issues, patch de statut."""

from datetime import UTC, datetime

import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_gtm_checker, get_stack_detector, get_tls_checker
from app.main import app
from app.models.enums import StackKind
from app.models.user import User
from app.models.website import Website
from app.services.stack_detector import StackDetection
from app.services.tls_check import TlsStatus


@pytest_asyncio.fixture
async def mock_detector():
    async def _fake(url: str) -> StackDetection:
        _ = url
        return StackDetection(StackKind.NEXTJS, ("test",), 0.9)

    async def _fake_tls(domain: str) -> TlsStatus:
        return TlsStatus(host=domain, status="valid", checked_at=datetime.now(UTC))

    async def _fake_gtm(domain: str) -> None:
        _ = domain
        return None

    app.dependency_overrides[get_stack_detector] = lambda: _fake
    app.dependency_overrides[get_tls_checker] = lambda: _fake_tls
    app.dependency_overrides[get_gtm_checker] = lambda: _fake_gtm
    yield
    app.dependency_overrides.pop(get_stack_detector, None)
    app.dependency_overrides.pop(get_tls_checker, None)
    app.dependency_overrides.pop(get_gtm_checker, None)


async def _website(session: AsyncSession, *, user: User, domain: str) -> Website:
    site = Website(user_id=user.id, domain=domain, display_name=domain.split(".", maxsplit=1)[0])
    session.add(site)
    await session.flush()
    return site


async def test_scan_updates_stack_and_creates_issues(
    authed_client: tuple[AsyncClient, User],
    db_session: AsyncSession,
    mock_detector: None,
) -> None:
    client, user = authed_client
    site = await _website(db_session, user=user, domain="boutique-verte.fr")

    resp = await client.post(f"/api/v1/websites/{site.id}/scan")
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["detected_stack"] == "nextjs"
    assert body["metrics"]["ga4"]["score"] == 92
    assert body["issues"]["created"] >= 3

    await db_session.refresh(site)
    assert site.detected_stack is StackKind.NEXTJS

    # 2e scan : rien de nouveau, tout est "updated"
    again = (await client.post(f"/api/v1/websites/{site.id}/scan")).json()
    assert again["issues"]["created"] == 0
    assert again["issues"]["updated"] >= 3


async def test_overview_shape(
    authed_client: tuple[AsyncClient, User],
    db_session: AsyncSession,
    mock_detector: None,
) -> None:
    client, user = authed_client
    site = await _website(db_session, user=user, domain="boutique-verte.fr")
    await client.post(f"/api/v1/websites/{site.id}/scan")

    resp = await client.get(f"/api/v1/websites/{site.id}/overview")
    assert resp.status_code == 200
    body = resp.json()

    assert body["stack"] == "nextjs"
    assert body["last_scan_hours_ago"] == 0
    assert [m["id"] for m in body["metrics"]] == ["ga4", "gsc", "cwv"]
    assert body["recommendation"]["severity"] == "high"
    assert "purchase" in body["recommendation"]["title"].lower()
    assert body["recommendation"]["cta_kind"] == "gtm"
    assert len(body["events"]) == 1
    assert body["events"][0]["kind"] == "scan"
    assert body["events"][0]["result"] == "success"


async def test_audit_endpoint_composes_diagnostics(
    authed_client: tuple[AsyncClient, User],
    db_session: AsyncSession,
    mock_detector: None,
) -> None:
    client, user = authed_client
    site = await _website(db_session, user=user, domain="boutique-verte.fr")
    await client.post(f"/api/v1/websites/{site.id}/scan")

    resp = await client.get(f"/api/v1/websites/{site.id}/audit")
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["domain"] == "boutique-verte.fr"
    assert body["captured_at"] is not None
    assert [v["id"] for v in body["vitals"]] == ["lcp", "inp", "cls"]

    lcp = next(v for v in body["vitals"] if v["id"] == "lcp")
    assert lcp["rating"] == "warn"  # 3400 ms
    assert lcp["diagnostic"]["source"] == "field"
    assert {a["name"] for a in lcp["diagnostic"]["assets"]} == {
        "hero-banner.jpg",
        "collection-2026-large.png",
    }
    assert lcp["diagnostic"]["preload_hint"].startswith('<link rel="preload"')

    inp = next(v for v in body["vitals"] if v["id"] == "inp")
    entities = {e["name"]: e for e in inp["diagnostic"]["entities"]}
    assert entities["Google Tag Manager"]["main_thread_ms"] == 480
    assert inp["diagnostic"]["total_blocking_time_ms"] == 640

    cls = next(v for v in body["vitals"] if v["id"] == "cls")
    assert any(s["selector"] == "div.promo-bar" for s in cls["diagnostic"]["shift_elements"])

    assert any(e["name"] == "purchase" for e in body["ga4"]["events"])
    assert any("noindex" in r["label"] for r in body["index"]["reasons"])

    urls = {u["url"]: u for u in body["urls"]}
    assert len(urls) >= 8
    # CTR calcule cote serveur
    edition = urls["/produits/edition-limitee"]
    assert edition["ctr"] == round(5 / 5200 * 100, 1)
    assert "Title" in edition["marketing_action"]  # gros volume + CTR ridicule
    assert "noindex" in urls["/panier"]["marketing_action"].lower()
    assert "indexation" in urls["/collections/soldes-ete"]["marketing_action"].lower()
    assert urls["/blog/entretien-laine"]["marketing_action"].startswith("Renforcer le maillage")


async def test_audit_endpoint_404_before_scan(
    authed_client: tuple[AsyncClient, User],
    db_session: AsyncSession,
) -> None:
    client, user = authed_client
    site = await _website(db_session, user=user, domain="fresh-site.com")
    resp = await client.get(f"/api/v1/websites/{site.id}/audit")
    assert resp.status_code == 404


async def test_issues_list_and_filters(
    authed_client: tuple[AsyncClient, User],
    db_session: AsyncSession,
    mock_detector: None,
) -> None:
    client, user = authed_client
    site = await _website(db_session, user=user, domain="boutique-verte.fr")
    await client.post(f"/api/v1/websites/{site.id}/scan")

    everything = (await client.get(f"/api/v1/websites/{site.id}/issues")).json()
    assert len(everything) >= 3

    todo = (await client.get(f"/api/v1/websites/{site.id}/issues?status=todo")).json()
    assert len(todo) == len(everything)
    assert all(i["status"] == "todo" for i in todo)

    crit = (await client.get(f"/api/v1/websites/{site.id}/issues?severity=critical")).json()
    assert len(crit) == 1
    assert crit[0]["severity"] == "critical"


async def test_patch_issue_status_transitions(
    authed_client: tuple[AsyncClient, User],
    db_session: AsyncSession,
    mock_detector: None,
) -> None:
    client, user = authed_client
    site = await _website(db_session, user=user, domain="boutique-verte.fr")
    await client.post(f"/api/v1/websites/{site.id}/scan")
    issue_id = (await client.get(f"/api/v1/websites/{site.id}/issues")).json()[0]["id"]

    started = await client.patch(
        f"/api/v1/websites/{site.id}/issues/{issue_id}", json={"status": "in_progress"}
    )
    assert started.status_code == 200
    assert started.json()["status"] == "in_progress"
    assert started.json()["resolved_at"] is None

    done = await client.patch(
        f"/api/v1/websites/{site.id}/issues/{issue_id}", json={"status": "resolved"}
    )
    assert done.status_code == 200
    assert done.json()["status"] == "fixed"
    assert done.json()["resolved_at"] is not None

    bad = await client.patch(
        f"/api/v1/websites/{site.id}/issues/{issue_id}", json={"status": "banana"}
    )
    assert bad.status_code == 422


async def test_scan_rejects_foreign_website(
    authed_client: tuple[AsyncClient, User],
    db_session: AsyncSession,
    make_user,
    mock_detector: None,
) -> None:
    client, _user = authed_client
    stranger = await make_user(sub="stranger-audit")
    foreign = await _website(db_session, user=stranger, domain="notyours.com")

    resp = await client.post(f"/api/v1/websites/{foreign.id}/scan")
    assert resp.status_code == 404


async def test_endpoints_require_auth(db_client: AsyncClient) -> None:
    fake_id = "00000000-0000-0000-0000-000000000000"
    assert (await db_client.post(f"/api/v1/websites/{fake_id}/scan")).status_code == 401
    assert (await db_client.get(f"/api/v1/websites/{fake_id}/overview")).status_code == 401
    assert (await db_client.get(f"/api/v1/websites/{fake_id}/issues")).status_code == 401
    assert (await db_client.get(f"/api/v1/websites/{fake_id}/audit")).status_code == 401
