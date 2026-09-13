"""Boucle de conversation : historique -> appel LLM -> outils -> persistance.

Le cap quotidien de messages se verifie AVANT d'appeler cette fonction (dans
l'endpoint, avant d'ouvrir le flux SSE) ; ici on incremente seulement.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, date, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.advisor import AdvisorMessage, AdvisorThread, AdvisorUsage, UserAdvisorSettings
from app.models.website import Website
from app.services.advisor.context_builder import build_context
from app.services.advisor.llm import AdvisorLLM, TurnDelta, TurnResult
from app.services.advisor.personas import PERSONA_DEFAULT, build_system
from app.services.advisor.tools import TOOL_DEFS, ToolContext, dispatch
from app.services.audit_engine import Detector, GtmChecker, TlsChecker
from app.services.audit_probe import AuditProbe
from app.services.gtm_headless import GtmHeadlessVerifier


class AdvisorMessageCapReached(Exception):
    """Le quota quotidien de messages de l'utilisateur est atteint."""


async def _usage_row(session: AsyncSession, workspace_id: UUID, day: date) -> AdvisorUsage:
    row = (
        await session.execute(
            select(AdvisorUsage).where(
                AdvisorUsage.workspace_id == workspace_id, AdvisorUsage.day == day
            )
        )
    ).scalar_one_or_none()
    if row is None:
        row = AdvisorUsage(workspace_id=workspace_id, day=day, brief_count=0, message_count=0)
        session.add(row)
        await session.flush()
    return row


async def _load_history(session: AsyncSession, thread_id: UUID) -> list[dict]:
    rows = (
        await session.execute(
            select(AdvisorMessage)
            .where(AdvisorMessage.thread_id == thread_id)
            .order_by(AdvisorMessage.created_at)
        )
    ).scalars().all()
    return [{"role": r.role, "content": r.blocks} for r in rows]


def _record(
    *, thread_id: UUID, role: str, blocks: list[dict], text: str = "", usage: dict | None = None
) -> AdvisorMessage:
    return AdvisorMessage(
        thread_id=thread_id, role=role, blocks=blocks, text=text, usage=usage, status="complete"
    )


async def run_chat_turn(
    session: AsyncSession,
    *,
    thread: AdvisorThread,
    website: Website,
    user_id: UUID,
    workspace_id: UUID,
    llm: AdvisorLLM,
    user_text: str,
    iteration_cap: int,
    probe: AuditProbe | None = None,
    detector: Detector | None = None,
    tls_checker: TlsChecker | None = None,
    gtm_checker: GtmChecker | None = None,
    gtm_headless_verifier: GtmHeadlessVerifier | None = None,
) -> AsyncIterator[dict]:
    settings_row = await session.get(UserAdvisorSettings, user_id)
    persona_key = settings_row.persona_key if settings_row else PERSONA_DEFAULT
    custom_prompt = settings_row.custom_prompt if settings_row else None

    history = await _load_history(session, thread.id)

    user_blocks = [{"type": "text", "text": user_text}]
    session.add(_record(thread_id=thread.id, role="user", blocks=user_blocks, text=user_text))
    await session.flush()

    messages = [*history, {"role": "user", "content": user_blocks}]
    context = await build_context(session, website)
    system = build_system(persona_key, custom_prompt, mode="chat")
    system = [
        *system,
        {
            "type": "text",
            "text": "Contexte actuel du site :\n" + context,
            "cache_control": {"type": "ephemeral"},
        },
    ]

    total_usage = {"input": 0, "output": 0, "cache_read": 0, "cache_creation": 0}
    ctx = ToolContext(
        session=session,
        website=website,
        user_id=user_id,
        thread_id=thread.id,
        probe=probe,
        detector=detector,
        tls_checker=tls_checker,
        gtm_checker=gtm_checker,
        gtm_headless_verifier=gtm_headless_verifier,
    )

    for _ in range(iteration_cap):
        result: TurnResult | None = None
        async for chunk in llm.stream_turn(system=system, messages=messages, tools=TOOL_DEFS):
            if isinstance(chunk, TurnDelta):
                yield {"kind": "token", "text": chunk.text}
            else:
                result = chunk
        assert result is not None
        for key in total_usage:
            total_usage[key] += result.usage.get(key, 0)

        if result.stop_reason != "tool_use":
            final_text = "".join(
                b.get("text", "") for b in result.content if b.get("type") == "text"
            )
            session.add(
                _record(
                    thread_id=thread.id,
                    role="assistant",
                    blocks=result.content,
                    text=final_text,
                    usage=total_usage,
                )
            )
            usage_row = await _usage_row(session, workspace_id, datetime.now(UTC).date())
            usage_row.message_count += 1
            await session.flush()
            yield {"kind": "done", "usage": total_usage}
            return

        tool_uses = [b for b in result.content if b.get("type") == "tool_use"]
        tool_results = []
        for call in tool_uses:
            yield {"kind": "tool_call", "tool": call["name"]}
            output = await dispatch(call["name"], call.get("input") or {}, ctx)
            tool_results.append(
                {"type": "tool_result", "tool_use_id": call["id"], "content": str(output)}
            )
            yield {"kind": "tool_result", "tool": call["name"]}

        session.add(_record(thread_id=thread.id, role="assistant", blocks=result.content))
        session.add(_record(thread_id=thread.id, role="user", blocks=tool_results))
        await session.flush()

        messages.append({"role": "assistant", "content": result.content})
        messages.append({"role": "user", "content": tool_results})

    yield {"kind": "error", "text": "Trop d'étapes pour répondre — réessaie ou reformule ta question."}
