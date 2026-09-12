from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.advisor import AdvisorMessage, AdvisorThread, AdvisorUsage, UserAdvisorSettings
from app.models.audit_snapshot import AuditSnapshot
from app.models.enums import SnapshotSource
from app.models.website import Website
from app.services.advisor.llm import MockAdvisorLLM
from app.services.advisor.service import AdvisorCapReached, generate_brief
from tests.conftest import UserFactory


async def _site_with_snapshot(db_session: AsyncSession, user_id) -> Website:
    site = Website(user_id=user_id, domain="svc.test", display_name="Svc")
    db_session.add(site)
    await db_session.flush()
    db_session.add(
        AuditSnapshot(
            website_id=site.id,
            captured_at=datetime(2026, 9, 1, tzinfo=UTC),
            source=SnapshotSource.COMPOSITE,
            metrics={"ga4": {"score": 80}, "gsc": {"score": 80}, "cwv": {"score": 80}},
        )
    )
    await db_session.flush()
    return site


async def test_generate_brief_persists_thread_message_and_usage(
    db_session: AsyncSession, make_user: UserFactory
) -> None:
    user = await make_user(sub="svc-1")
    site = await _site_with_snapshot(db_session, user.id)

    outcome = await generate_brief(
        db_session,
        website=site,
        user_id=user.id,
        workspace_id=site.workspace_id,
        llm=MockAdvisorLLM(),
        daily_cap=5,
    )

    thread = await db_session.get(AdvisorThread, outcome.thread_id)
    assert thread is not None and thread.website_id == site.id
    assert thread.title.startswith("Plan d'action")
    msg = await db_session.get(AdvisorMessage, outcome.message_id)
    assert msg.role == "assistant" and msg.status == "complete"
    assert "## Synthèse" in msg.text
    assert msg.blocks == [{"type": "text", "text": msg.text}]

    usage = (
        await db_session.execute(select(AdvisorUsage).where(AdvisorUsage.user_id == user.id))
    ).scalar_one()
    assert usage.brief_count == 1


async def test_second_call_increments_usage(
    db_session: AsyncSession, make_user: UserFactory
) -> None:
    user = await make_user(sub="svc-2")
    site = await _site_with_snapshot(db_session, user.id)
    for _ in range(2):
        await generate_brief(
            db_session,
            website=site,
            user_id=user.id,
            workspace_id=site.workspace_id,
            llm=MockAdvisorLLM(),
            daily_cap=5,
        )
    usage = (
        await db_session.execute(select(AdvisorUsage).where(AdvisorUsage.user_id == user.id))
    ).scalar_one()
    assert usage.brief_count == 2


async def test_cap_reached_raises_and_persists_nothing_more(
    db_session: AsyncSession, make_user: UserFactory
) -> None:
    user = await make_user(sub="svc-3")
    site = await _site_with_snapshot(db_session, user.id)
    await generate_brief(
        db_session,
        website=site,
        user_id=user.id,
        workspace_id=site.workspace_id,
        llm=MockAdvisorLLM(),
        daily_cap=1,
    )
    with pytest.raises(AdvisorCapReached):
        await generate_brief(
            db_session,
            website=site,
            user_id=user.id,
            workspace_id=site.workspace_id,
            llm=MockAdvisorLLM(),
            daily_cap=1,
        )
    count = (
        await db_session.execute(
            select(func.count()).select_from(AdvisorThread).where(AdvisorThread.website_id == site.id)
        )
    ).scalar_one()
    assert count == 1


async def test_uses_saved_persona(db_session: AsyncSession, make_user: UserFactory) -> None:
    user = await make_user(sub="svc-4")
    site = await _site_with_snapshot(db_session, user.id)
    db_session.add(UserAdvisorSettings(user_id=user.id, persona_key="technique"))
    await db_session.flush()
    outcome = await generate_brief(
        db_session,
        website=site,
        user_id=user.id,
        workspace_id=site.workspace_id,
        llm=MockAdvisorLLM(),
        daily_cap=5,
    )
    thread = await db_session.get(AdvisorThread, outcome.thread_id)
    assert thread.persona_key == "technique"


async def test_llm_error_propagates_nothing_persisted(
    db_session: AsyncSession, make_user: UserFactory
) -> None:
    user = await make_user(sub="svc-5")
    site = await _site_with_snapshot(db_session, user.id)
    with pytest.raises(RuntimeError):
        await generate_brief(
            db_session,
            website=site,
            user_id=user.id,
            workspace_id=site.workspace_id,
            llm=MockAdvisorLLM(raises=RuntimeError("api down")),
            daily_cap=5,
        )
    count = (
        await db_session.execute(select(func.count()).select_from(AdvisorThread))
    ).scalar_one()
    assert count == 0
