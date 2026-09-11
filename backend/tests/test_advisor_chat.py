from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.advisor import AdvisorMessage, AdvisorThread, AdvisorUsage
from app.models.audit_snapshot import AuditSnapshot
from app.models.enums import SnapshotSource, StackKind
from app.models.website import Website
from app.services.advisor.chat import run_chat_turn
from app.services.advisor.llm import MockAdvisorLLM, TurnResult
from app.services.audit_probe import MockAuditProbe
from app.services.stack_detector import StackDetection
from app.services.tls_check import TlsStatus
from tests.conftest import UserFactory

_ZERO = {"input": 0, "output": 0, "cache_read": 0, "cache_creation": 0}


async def _thread_with_snapshot(
    db_session: AsyncSession, user_id
) -> tuple[Website, AdvisorThread]:
    site = Website(user_id=user_id, domain="chat.test", display_name="Chat")
    db_session.add(site)
    await db_session.flush()
    db_session.add(
        AuditSnapshot(
            website_id=site.id,
            captured_at=datetime.now(UTC),
            source=SnapshotSource.COMPOSITE,
            metrics={"ga4": {"score": 70}},
        )
    )
    thread = AdvisorThread(
        website_id=site.id,
        persona_key="consultant",
        title="Plan d'action — test",
        source_snapshot_id=None,
    )
    db_session.add(thread)
    await db_session.flush()
    return site, thread


async def _collect(gen):
    return [e async for e in gen]


async def _messages(db_session: AsyncSession, thread_id) -> list[AdvisorMessage]:
    return list(
        (
            await db_session.execute(
                select(AdvisorMessage)
                .where(AdvisorMessage.thread_id == thread_id)
                .order_by(AdvisorMessage.created_at)
            )
        )
        .scalars()
        .all()
    )


async def test_simple_reply_persists_user_and_assistant_messages(
    db_session: AsyncSession, make_user: UserFactory
) -> None:
    user = await make_user(sub="chat-1")
    site, thread = await _thread_with_snapshot(db_session, user.id)
    llm = MockAdvisorLLM(
        turns=[
            TurnResult(
                content=[{"type": "text", "text": "Reponse directe."}],
                stop_reason="end_turn",
                usage=dict(_ZERO),
            ),
        ]
    )

    events = await _collect(
        run_chat_turn(
            db_session,
            thread=thread,
            website=site,
            user_id=user.id,
            llm=llm,
            user_text="Quel est mon score GA4 ?",
            iteration_cap=6,
        )
    )

    assert events[-1]["kind"] == "done"
    rows = await _messages(db_session, thread.id)
    assert [r.role for r in rows] == ["user", "assistant"]
    assert rows[0].text == "Quel est mon score GA4 ?"
    assert rows[1].text == "Reponse directe."

    usage = (
        await db_session.execute(select(AdvisorUsage).where(AdvisorUsage.user_id == user.id))
    ).scalar_one()
    assert usage.message_count == 1


async def test_tool_use_turn_executes_tool_and_continues(
    db_session: AsyncSession, make_user: UserFactory
) -> None:
    user = await make_user(sub="chat-2")
    site, thread = await _thread_with_snapshot(db_session, user.id)
    llm = MockAdvisorLLM(
        turns=[
            TurnResult(
                content=[
                    {"type": "tool_use", "id": "t1", "name": "get_score_history", "input": {"days": 30}}
                ],
                stop_reason="tool_use",
                usage=dict(_ZERO),
            ),
            TurnResult(
                content=[{"type": "text", "text": "Ton score GA4 est 70."}],
                stop_reason="end_turn",
                usage=dict(_ZERO),
            ),
        ]
    )

    events = await _collect(
        run_chat_turn(
            db_session,
            thread=thread,
            website=site,
            user_id=user.id,
            llm=llm,
            user_text="Et avant ?",
            iteration_cap=6,
        )
    )

    kinds = [e["kind"] for e in events]
    assert "tool_call" in kinds
    assert "tool_result" in kinds
    assert kinds[-1] == "done"

    rows = await _messages(db_session, thread.id)
    roles = [r.role for r in rows]
    assert roles == ["user", "assistant", "user", "assistant"]
    assert rows[1].blocks[0]["name"] == "get_score_history"
    assert rows[2].blocks[0]["type"] == "tool_result"
    assert rows[3].text == "Ton score GA4 est 70."


async def test_iteration_cap_stops_infinite_tool_loop(
    db_session: AsyncSession, make_user: UserFactory
) -> None:
    user = await make_user(sub="chat-3")
    site, thread = await _thread_with_snapshot(db_session, user.id)
    forever = TurnResult(
        content=[{"type": "tool_use", "id": "t", "name": "get_gtm_check", "input": {}}],
        stop_reason="tool_use",
        usage=dict(_ZERO),
    )
    llm = MockAdvisorLLM(turns=[forever] * 10)

    events = await _collect(
        run_chat_turn(
            db_session,
            thread=thread,
            website=site,
            user_id=user.id,
            llm=llm,
            user_text="boucle",
            iteration_cap=3,
        )
    )
    assert events[-1]["kind"] == "error"


async def test_history_is_reloaded_on_second_message(
    db_session: AsyncSession, make_user: UserFactory
) -> None:
    user = await make_user(sub="chat-4")
    site, thread = await _thread_with_snapshot(db_session, user.id)
    llm = MockAdvisorLLM(
        turns=[
            TurnResult(
                content=[{"type": "text", "text": "Premiere reponse."}],
                stop_reason="end_turn",
                usage=dict(_ZERO),
            ),
        ]
    )
    await _collect(
        run_chat_turn(
            db_session, thread=thread, website=site, user_id=user.id,
            llm=llm, user_text="Question 1", iteration_cap=6,
        )
    )

    llm2 = MockAdvisorLLM(
        turns=[
            TurnResult(
                content=[{"type": "text", "text": "Deuxieme reponse."}],
                stop_reason="end_turn",
                usage=dict(_ZERO),
            ),
        ]
    )
    await _collect(
        run_chat_turn(
            db_session, thread=thread, website=site, user_id=user.id,
            llm=llm2, user_text="Question 2", iteration_cap=6,
        )
    )

    rows = await _messages(db_session, thread.id)
    assert len(rows) == 4


async def test_chat_can_trigger_rescan_via_tool(
    db_session: AsyncSession, make_user: UserFactory
) -> None:
    user = await make_user(sub="chat-5")
    site, thread = await _thread_with_snapshot(db_session, user.id)

    async def detector(url: str, **kw):
        _ = (url, kw)
        return StackDetection(StackKind.REACT, ("react-root-static",), 0.7)

    async def tls_checker(domain: str):
        return TlsStatus(host=domain, status="valid", checked_at=datetime.now(UTC))

    llm = MockAdvisorLLM(
        turns=[
            TurnResult(
                content=[
                    {"type": "tool_use", "id": "t1", "name": "trigger_rescan", "input": {}}
                ],
                stop_reason="tool_use",
                usage=dict(_ZERO),
            ),
            TurnResult(
                content=[{"type": "text", "text": "Diagnostic relance."}],
                stop_reason="end_turn",
                usage=dict(_ZERO),
            ),
        ]
    )

    events = await _collect(
        run_chat_turn(
            db_session,
            thread=thread,
            website=site,
            user_id=user.id,
            llm=llm,
            user_text="relance un scan",
            iteration_cap=6,
            probe=MockAuditProbe(),
            detector=detector,
            tls_checker=tls_checker,
        )
    )
    assert events[-1]["kind"] == "done"

    rows = await _messages(db_session, thread.id)
    tool_msg = next(r for r in rows if r.blocks and r.blocks[0].get("name") == "trigger_rescan")
    assert tool_msg is not None
