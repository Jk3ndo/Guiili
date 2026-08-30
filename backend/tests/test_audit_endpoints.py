"""Endpoints d'audit : scan, overview, issues, patch de statut."""

import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_stack_detector
from app.main import app
from app.models.enums import StackKind
from app.models.user import User
from app.models.website import Website
from app.services.stack_detector import StackDetection


@pytest_asyncio.fixture
async def mock_detector():
    async def _fake(url: str) -> StackDetection:
        _ = url
        return StackDetection(StackKind.NEXTJS, ("test",), 0.9)

    app.dependency_overrides[get_stack_detector] = lambda: _fake
    yield
    app.dependency_overrides.pop(get_stack_detector, None)


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

    resp = await client.post(f"/websites/{site.id}/scan")
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["detected_stack"] == "nextjs"
    assert body["metrics"]["ga4"]["score"] == 92
    assert body["issues"]["created"] >= 3

    await db_session.refresh(site)
    assert site.detected_stack is StackKind.NEXTJS

    # 2e scan : rien de nouveau, tout est "updated"
    again = (await client.post(f"/websites/{site.id}/scan")).json()
    assert again["issues"]["created"] == 0
    assert again["issues"]["updated"] >= 3


async def test_overview_shape(
    authed_client: tuple[AsyncClient, User],
    db_session: AsyncSession,
    mock_detector: None,
) -> None:
    client, user = authed_client
    site = await _website(db_session, user=user, domain="boutique-verte.fr")
    await client.post(f"/websites/{site.id}/scan")

    resp = await client.get(f"/websites/{site.id}/overview")
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


async def test_issues_list_and_filters(
    authed_client: tuple[AsyncClient, User],
    db_session: AsyncSession,
    mock_detector: None,
) -> None:
    client, user = authed_client
    site = await _website(db_session, user=user, domain="boutique-verte.fr")
    await client.post(f"/websites/{site.id}/scan")

    everything = (await client.get(f"/websites/{site.id}/issues")).json()
    assert len(everything) >= 3

    todo = (await client.get(f"/websites/{site.id}/issues?status=todo")).json()
    assert len(todo) == len(everything)
    assert all(i["status"] == "todo" for i in todo)

    crit = (await client.get(f"/websites/{site.id}/issues?severity=critical")).json()
    assert len(crit) == 1
    assert crit[0]["severity"] == "critical"


async def test_patch_issue_status_transitions(
    authed_client: tuple[AsyncClient, User],
    db_session: AsyncSession,
    mock_detector: None,
) -> None:
    client, user = authed_client
    site = await _website(db_session, user=user, domain="boutique-verte.fr")
    await client.post(f"/websites/{site.id}/scan")
    issue_id = (await client.get(f"/websites/{site.id}/issues")).json()[0]["id"]

    started = await client.patch(
        f"/websites/{site.id}/issues/{issue_id}", json={"status": "in_progress"}
    )
    assert started.status_code == 200
    assert started.json()["status"] == "in_progress"
    assert started.json()["resolved_at"] is None

    done = await client.patch(f"/websites/{site.id}/issues/{issue_id}", json={"status": "resolved"})
    assert done.status_code == 200
    assert done.json()["status"] == "fixed"
    assert done.json()["resolved_at"] is not None

    bad = await client.patch(f"/websites/{site.id}/issues/{issue_id}", json={"status": "banana"})
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

    resp = await client.post(f"/websites/{foreign.id}/scan")
    assert resp.status_code == 404


async def test_endpoints_require_auth(db_client: AsyncClient) -> None:
    fake_id = "00000000-0000-0000-0000-000000000000"
    assert (await db_client.post(f"/websites/{fake_id}/scan")).status_code == 401
    assert (await db_client.get(f"/websites/{fake_id}/overview")).status_code == 401
    assert (await db_client.get(f"/websites/{fake_id}/issues")).status_code == 401
