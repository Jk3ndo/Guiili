"""Orchestration du brief : cap quotidien -> persona -> contexte -> LLM -> persistance.

Ne commit pas : l'appelant (endpoint) commit en cas de succes. Sur erreur du
LLM, l'exception remonte et rien n'est commite.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.advisor import AdvisorMessage, AdvisorThread, AdvisorUsage, UserAdvisorSettings
from app.models.audit_snapshot import AuditSnapshot
from app.models.website import Website
from app.services.advisor.context_builder import build_context
from app.services.advisor.llm import AdvisorLLM
from app.services.advisor.personas import PERSONA_DEFAULT, build_system


class AdvisorCapReached(Exception):
    """Le quota quotidien de briefs de l'utilisateur est atteint."""


@dataclass(frozen=True, slots=True)
class BriefOutcome:
    thread_id: UUID
    message_id: UUID
    content: str
    usage: dict


async def _usage_row(session: AsyncSession, user_id: UUID, day) -> AdvisorUsage:
    row = (
        await session.execute(
            select(AdvisorUsage).where(
                AdvisorUsage.user_id == user_id, AdvisorUsage.day == day
            )
        )
    ).scalar_one_or_none()
    if row is None:
        row = AdvisorUsage(user_id=user_id, day=day, brief_count=0, message_count=0)
        session.add(row)
        await session.flush()
    return row


async def generate_brief(
    session: AsyncSession,
    *,
    website: Website,
    user_id: UUID,
    llm: AdvisorLLM,
    daily_cap: int,
) -> BriefOutcome:
    now = datetime.now(UTC)
    usage = await _usage_row(session, user_id, now.date())
    if usage.brief_count >= daily_cap:
        raise AdvisorCapReached(
            f"Limite quotidienne de briefs atteinte ({daily_cap}). Réessaie demain."
        )

    settings = await session.get(UserAdvisorSettings, user_id)
    persona_key = settings.persona_key if settings else PERSONA_DEFAULT
    custom_prompt = settings.custom_prompt if settings else None

    system = build_system(persona_key, custom_prompt)
    context = await build_context(session, website)

    latest_snapshot_id = (
        await session.execute(
            select(AuditSnapshot.id)
            .where(AuditSnapshot.website_id == website.id)
            .order_by(AuditSnapshot.captured_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    result = await llm.generate_brief(system=system, context=context)

    thread = AdvisorThread(
        website_id=website.id,
        persona_key=persona_key,
        custom_prompt_snapshot=custom_prompt if persona_key == "custom" else None,
        title=f"Plan d'action — {now.date().isoformat()}",
        source_snapshot_id=latest_snapshot_id,
    )
    session.add(thread)
    await session.flush()

    message = AdvisorMessage(
        thread_id=thread.id,
        role="assistant",
        blocks=[{"type": "text", "text": result.text}],
        text=result.text,
        usage=result.usage,
        status="complete",
    )
    session.add(message)
    await session.flush()

    usage.brief_count += 1
    await session.flush()

    return BriefOutcome(
        thread_id=thread.id,
        message_id=message.id,
        content=result.text,
        usage=result.usage,
    )


async def message_count(session: AsyncSession, thread_id: UUID) -> int:
    return (
        await session.execute(
            select(func.count())
            .select_from(AdvisorMessage)
            .where(AdvisorMessage.thread_id == thread_id)
        )
    ).scalar_one()
