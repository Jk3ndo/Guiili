"""Endpoints du conseiller : reglages persona, brief, fils de discussion."""

import json
import uuid
from datetime import UTC, datetime

import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_advisor_llm
from app.config import get_settings
from app.main import app
from app.models.advisor import AdvisorThread
from app.models.audit_snapshot import AuditSnapshot
from app.models.enums import SnapshotSource
from app.models.user import User
from app.models.website import Website
from app.services.advisor.llm import MockAdvisorLLM, TurnResult

_ZERO = {"input": 0, "output": 0, "cache_read": 0, "cache_creation": 0}


async def _sse_events(client: AsyncClient, url: str, **kwargs) -> list[dict]:
    events: list[dict] = []
    async with client.stream("POST", url, **kwargs) as resp:
        assert resp.status_code == 200, await resp.aread()
        async for line in resp.aiter_lines():
            if line.startswith("data: "):
                events.append(json.loads(line[len("data: ") :]))
    return events


@pytest_asyncio.fixture
def mock_advisor():
    stub = MockAdvisorLLM()
    app.dependency_overrides[get_advisor_llm] = lambda: stub
    yield
    app.dependency_overrides.pop(get_advisor_llm, None)


async def _site(db_session: AsyncSession, *, user: User, domain: str = "adv.test") -> Website:
    site = Website(user_id=user.id, domain=domain, display_name=domain.partition(".")[0])
    db_session.add(site)
    await db_session.flush()
    db_session.add(
        AuditSnapshot(
            website_id=site.id,
            captured_at=datetime.now(UTC),
            source=SnapshotSource.COMPOSITE,
            metrics={"ga4": {"score": 70}, "gsc": {"score": 70}, "cwv": {"score": 70}},
        )
    )
    await db_session.flush()
    return site


async def test_get_settings_defaults_to_consultant(
    authed_client: tuple[AsyncClient, User], db_session: AsyncSession
) -> None:
    client, _ = authed_client
    resp = await client.get("/api/v1/advisor/settings")
    assert resp.status_code == 200
    body = resp.json()
    assert body["persona_key"] == "consultant"
    assert body["custom_prompt"] is None
    assert {p["key"] for p in body["presets"]} >= {"consultant", "technique"}


async def test_put_settings_persists_and_validates(
    authed_client: tuple[AsyncClient, User], db_session: AsyncSession
) -> None:
    client, _ = authed_client

    ok = await client.put("/api/v1/advisor/settings", json={"persona_key": "technique"})
    assert ok.status_code == 200
    assert (await client.get("/api/v1/advisor/settings")).json()["persona_key"] == "technique"

    custom = await client.put(
        "/api/v1/advisor/settings",
        json={"persona_key": "custom", "custom_prompt": "  Sois bref.  "},
    )
    assert custom.status_code == 200
    assert custom.json()["custom_prompt"] == "Sois bref."

    assert (
        await client.put("/api/v1/advisor/settings", json={"persona_key": "custom", "custom_prompt": ""})
    ).status_code == 422
    assert (
        await client.put("/api/v1/advisor/settings", json={"persona_key": "zzz"})
    ).status_code == 422


async def test_brief_generates_thread_and_message(
    authed_client: tuple[AsyncClient, User],
    db_session: AsyncSession,
    mock_advisor: None,
) -> None:
    client, user = authed_client
    site = await _site(db_session, user=user)

    resp = await client.post(f"/api/v1/websites/{site.id}/advisor/brief")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "## Synthèse" in body["content"]
    assert set(body["usage"]) == {"input", "output", "cache_read", "cache_creation"}

    threads = (await client.get(f"/api/v1/websites/{site.id}/advisor/threads")).json()
    assert len(threads) == 1 and threads[0]["message_count"] == 1

    thread = (await client.get(f"/api/v1/advisor/threads/{body['thread_id']}")).json()
    assert thread["messages"][0]["role"] == "assistant"
    assert "## Synthèse" in thread["messages"][0]["text"]


async def test_brief_respects_daily_cap(
    authed_client: tuple[AsyncClient, User],
    db_session: AsyncSession,
    mock_advisor: None,
) -> None:
    client, user = authed_client
    site = await _site(db_session, user=user)
    cap = get_settings().advisor_daily_brief_cap

    for _ in range(cap):
        assert (await client.post(f"/api/v1/websites/{site.id}/advisor/brief")).status_code == 200
    assert (await client.post(f"/api/v1/websites/{site.id}/advisor/brief")).status_code == 429


async def test_brief_llm_error_returns_502_and_persists_nothing(
    authed_client: tuple[AsyncClient, User],
    db_session: AsyncSession,
) -> None:
    client, user = authed_client
    site = await _site(db_session, user=user)
    app.dependency_overrides[get_advisor_llm] = lambda: MockAdvisorLLM(
        raises=RuntimeError("api down")
    )
    try:
        resp = await client.post(f"/api/v1/websites/{site.id}/advisor/brief")
    finally:
        app.dependency_overrides.pop(get_advisor_llm, None)
    assert resp.status_code == 502
    assert (await client.get(f"/api/v1/websites/{site.id}/advisor/threads")).json() == []


async def test_brief_404_on_foreign_site(
    authed_client: tuple[AsyncClient, User],
    db_session: AsyncSession,
    mock_advisor: None,
) -> None:
    client, _ = authed_client
    other = User(email="other@x.com", google_sub="other-adv", display_name="Other")
    db_session.add(other)
    await db_session.flush()
    foreign = await _site(db_session, user=other, domain="foreign.test")
    assert (
        await client.post(f"/api/v1/websites/{foreign.id}/advisor/brief")
    ).status_code == 404


async def test_chat_message_streams_and_persists(
    authed_client: tuple[AsyncClient, User],
    db_session: AsyncSession,
    mock_advisor: None,
) -> None:
    client, user = authed_client
    site = await _site(db_session, user=user)
    brief = await client.post(f"/api/v1/websites/{site.id}/advisor/brief")
    thread_id = brief.json()["thread_id"]

    app.dependency_overrides[get_advisor_llm] = lambda: MockAdvisorLLM(
        turns=[
            TurnResult(
                content=[{"type": "text", "text": "Reponse en direct."}],
                stop_reason="end_turn",
                usage=dict(_ZERO),
            ),
        ]
    )
    try:
        events = await _sse_events(
            client,
            f"/api/v1/advisor/threads/{thread_id}/messages",
            json={"text": "Une question ?"},
        )
    finally:
        app.dependency_overrides[get_advisor_llm] = MockAdvisorLLM

    assert events[-1]["kind"] == "done"
    thread = (await client.get(f"/api/v1/advisor/threads/{thread_id}")).json()
    assert thread["messages"][-1]["text"] == "Reponse en direct."


async def test_chat_message_with_tool_use_exposes_blocks_on_reload(
    authed_client: tuple[AsyncClient, User],
    db_session: AsyncSession,
    mock_advisor: None,
) -> None:
    client, user = authed_client
    site = await _site(db_session, user=user)
    brief = await client.post(f"/api/v1/websites/{site.id}/advisor/brief")
    thread_id = brief.json()["thread_id"]

    app.dependency_overrides[get_advisor_llm] = lambda: MockAdvisorLLM(
        turns=[
            TurnResult(
                content=[
                    {"type": "tool_use", "id": "t1", "name": "get_gtm_check", "input": {}}
                ],
                stop_reason="tool_use",
                usage=dict(_ZERO),
            ),
            TurnResult(
                content=[{"type": "text", "text": "Voila."}],
                stop_reason="end_turn",
                usage=dict(_ZERO),
            ),
        ]
    )
    try:
        events = await _sse_events(
            client,
            f"/api/v1/advisor/threads/{thread_id}/messages",
            json={"text": "Check GTM ?"},
        )
    finally:
        app.dependency_overrides[get_advisor_llm] = MockAdvisorLLM

    assert any(e["kind"] == "tool_call" for e in events)
    thread = (await client.get(f"/api/v1/advisor/threads/{thread_id}")).json()
    tool_msgs = [
        m for m in thread["messages"] if any(b.get("type") == "tool_use" for b in m["blocks"])
    ]
    assert tool_msgs, "le tour tool_use doit rester visible via blocks au rechargement"


async def test_chat_message_respects_daily_cap(
    authed_client: tuple[AsyncClient, User],
    db_session: AsyncSession,
    mock_advisor: None,
) -> None:
    client, user = authed_client
    site = await _site(db_session, user=user)
    brief = await client.post(f"/api/v1/websites/{site.id}/advisor/brief")
    thread_id = brief.json()["thread_id"]
    cap = get_settings().advisor_daily_message_cap

    for _ in range(cap):
        await _sse_events(
            client, f"/api/v1/advisor/threads/{thread_id}/messages", json={"text": "x"}
        )
    resp = await client.post(
        f"/api/v1/advisor/threads/{thread_id}/messages", json={"text": "x"}
    )
    assert resp.status_code == 429


async def test_chat_message_404_on_unknown_thread(
    authed_client: tuple[AsyncClient, User],
) -> None:
    client, _ = authed_client
    resp = await client.post(
        f"/api/v1/advisor/threads/{uuid.uuid4()}/messages", json={"text": "x"}
    )
    assert resp.status_code == 404


async def test_archive_thread_hides_it_from_list(
    authed_client: tuple[AsyncClient, User],
    db_session: AsyncSession,
    mock_advisor: None,
) -> None:
    client, user = authed_client
    site = await _site(db_session, user=user)
    brief = await client.post(f"/api/v1/websites/{site.id}/advisor/brief")
    thread_id = brief.json()["thread_id"]

    resp = await client.delete(f"/api/v1/advisor/threads/{thread_id}")
    assert resp.status_code == 204

    threads = (await client.get(f"/api/v1/websites/{site.id}/advisor/threads")).json()
    assert threads == []

    with_archived = (
        await client.get(f"/api/v1/websites/{site.id}/advisor/threads?include_archived=true")
    ).json()
    assert len(with_archived) == 1


async def test_archive_thread_404_on_foreign_thread(
    authed_client: tuple[AsyncClient, User],
    db_session: AsyncSession,
    mock_advisor: None,
) -> None:
    client, _ = authed_client
    other = User(email="other2@x.com", google_sub="other-adv-2", display_name="Other2")
    db_session.add(other)
    await db_session.flush()
    foreign_site = await _site(db_session, user=other, domain="foreign2.test")
    foreign_thread = AdvisorThread(
        website_id=foreign_site.id, persona_key="consultant", title="Fil etranger"
    )
    db_session.add(foreign_thread)
    await db_session.flush()

    resp = await client.delete(f"/api/v1/advisor/threads/{foreign_thread.id}")
    assert resp.status_code == 404


async def test_endpoints_require_auth(db_client: AsyncClient) -> None:
    wid = uuid.uuid4()
    assert (await db_client.get("/api/v1/advisor/settings")).status_code == 401
    assert (
        await db_client.put("/api/v1/advisor/settings", json={"persona_key": "consultant"})
    ).status_code == 401
    assert (
        await db_client.post(f"/api/v1/websites/{wid}/advisor/brief")
    ).status_code == 401
    assert (
        await db_client.get(f"/api/v1/websites/{wid}/advisor/threads")
    ).status_code == 401
    assert (await db_client.get(f"/api/v1/advisor/threads/{wid}")).status_code == 401
    assert (
        await db_client.post(f"/api/v1/advisor/threads/{wid}/messages", json={"text": "x"})
    ).status_code == 401
    assert (await db_client.delete(f"/api/v1/advisor/threads/{wid}")).status_code == 401
