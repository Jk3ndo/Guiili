"""Agent conseiller : reglages de persona, generation du brief, fils de discussion.

Le brief est un POST bloquant (~20-40 s) : Claude streame en interne, l'endpoint
renvoie le texte complet. Le tchat, lui, streame vraiment vers le client (SSE) :
la boucle d'outils peut prendre plusieurs tours.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    AdvisorLLMDep,
    AuditProbeDep,
    CurrentUserDep,
    GtmCheckerDep,
    GtmHeadlessVerifierDep,
    SessionDep,
    SettingsDep,
    StackDetectorDep,
    TlsCheckerDep,
)
from app.models.advisor import AdvisorMessage, AdvisorThread, AdvisorUsage, UserAdvisorSettings
from app.models.user import User
from app.models.website import Website
from app.services.advisor.chat import AdvisorMessageCapReached, run_chat_turn
from app.services.advisor.personas import (
    PERSONA_DEFAULT,
    PERSONA_LABELS,
    PERSONA_PRESETS,
    validate_custom_prompt,
)
from app.services.advisor.service import AdvisorCapReached, generate_brief

router = APIRouter(tags=["advisor"])

_VALID_KEYS = set(PERSONA_PRESETS) | {"custom"}


async def _owned_website(session: AsyncSession, website_id: UUID, user: User) -> Website:
    site = await session.get(Website, website_id)
    if site is None or site.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="site introuvable")
    return site


# --------------------------------------------------------------------------- #
#  Schemas                                                                     #
# --------------------------------------------------------------------------- #


class PresetOut(BaseModel):
    key: str
    label: str


class SettingsOut(BaseModel):
    persona_key: str
    custom_prompt: str | None
    presets: list[PresetOut]


class SetSettingsRequest(BaseModel):
    persona_key: str
    custom_prompt: str | None = None

    @field_validator("persona_key")
    @classmethod
    def _known_key(cls, value: str) -> str:
        if value not in _VALID_KEYS:
            raise ValueError(f"persona inconnue : {value}")
        return value


class BriefOut(BaseModel):
    thread_id: UUID
    message_id: UUID
    content: str
    usage: dict


class ThreadSummaryOut(BaseModel):
    id: UUID
    title: str
    created_at: datetime
    message_count: int


class MessageOut(BaseModel):
    id: UUID
    role: str
    text: str
    blocks: list[dict]
    usage: dict | None
    created_at: datetime


class PostMessageRequest(BaseModel):
    text: str

    @field_validator("text")
    @classmethod
    def _clean_text(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("message vide")
        return cleaned[:4000]


class ThreadOut(BaseModel):
    id: UUID
    title: str
    persona_key: str
    created_at: datetime
    messages: list[MessageOut]


_PRESETS_OUT = [PresetOut(key=k, label=PERSONA_LABELS.get(k, k)) for k in PERSONA_PRESETS]


# --------------------------------------------------------------------------- #
#  Reglages de persona                                                         #
# --------------------------------------------------------------------------- #


@router.get("/advisor/settings", response_model=SettingsOut)
async def get_settings_endpoint(user: CurrentUserDep, session: SessionDep) -> SettingsOut:
    row = await session.get(UserAdvisorSettings, user.id)
    return SettingsOut(
        persona_key=row.persona_key if row else PERSONA_DEFAULT,
        custom_prompt=row.custom_prompt if row else None,
        presets=_PRESETS_OUT,
    )


@router.put("/advisor/settings", response_model=SettingsOut)
async def put_settings_endpoint(
    body: SetSettingsRequest, user: CurrentUserDep, session: SessionDep
) -> SettingsOut:
    custom = None
    if body.persona_key == "custom":
        try:
            custom = validate_custom_prompt(body.custom_prompt or "")
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    row = await session.get(UserAdvisorSettings, user.id)
    if row is None:
        row = UserAdvisorSettings(user_id=user.id)
        session.add(row)
    row.persona_key = body.persona_key
    row.custom_prompt = custom
    await session.commit()
    return SettingsOut(persona_key=row.persona_key, custom_prompt=row.custom_prompt, presets=_PRESETS_OUT)


# --------------------------------------------------------------------------- #
#  Brief                                                                       #
# --------------------------------------------------------------------------- #


@router.post("/websites/{website_id}/advisor/brief", response_model=BriefOut)
async def create_brief_endpoint(
    website_id: UUID,
    user: CurrentUserDep,
    session: SessionDep,
    llm: AdvisorLLMDep,
    settings: SettingsDep,
) -> BriefOut:
    site = await _owned_website(session, website_id, user)
    try:
        outcome = await generate_brief(
            session,
            website=site,
            user_id=user.id,
            llm=llm,
            daily_cap=settings.advisor_daily_brief_cap,
        )
    except AdvisorCapReached as exc:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(exc)) from exc
    except Exception as exc:  # tout echec LLM / reseau -> 502, rien de commite
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="le conseiller n'a pas pu répondre, réessaie dans un instant",
        ) from exc

    await session.commit()
    return BriefOut(
        thread_id=outcome.thread_id,
        message_id=outcome.message_id,
        content=outcome.content,
        usage=outcome.usage,
    )


# --------------------------------------------------------------------------- #
#  Fils de discussion                                                          #
# --------------------------------------------------------------------------- #


@router.get("/websites/{website_id}/advisor/threads", response_model=list[ThreadSummaryOut])
async def list_threads_endpoint(
    website_id: UUID, user: CurrentUserDep, session: SessionDep, include_archived: bool = False
) -> list[ThreadSummaryOut]:
    await _owned_website(session, website_id, user)
    stmt = select(AdvisorThread).where(AdvisorThread.website_id == website_id)
    if not include_archived:
        stmt = stmt.where(AdvisorThread.archived_at.is_(None))
    threads = list(
        (await session.execute(stmt.order_by(AdvisorThread.created_at.desc()))).scalars().all()
    )
    out: list[ThreadSummaryOut] = []
    for thread in threads:
        count = len(
            (
                await session.execute(
                    select(AdvisorMessage.id).where(AdvisorMessage.thread_id == thread.id)
                )
            )
            .scalars()
            .all()
        )
        out.append(
            ThreadSummaryOut(
                id=thread.id,
                title=thread.title,
                created_at=thread.created_at,
                message_count=count,
            )
        )
    return out


@router.get("/advisor/threads/{thread_id}", response_model=ThreadOut)
async def get_thread_endpoint(
    thread_id: UUID, user: CurrentUserDep, session: SessionDep
) -> ThreadOut:
    thread = await session.get(AdvisorThread, thread_id)
    if thread is None:
        raise HTTPException(status_code=404, detail="fil introuvable")
    await _owned_website(session, thread.website_id, user)

    messages = list(
        (
            await session.execute(
                select(AdvisorMessage)
                .where(AdvisorMessage.thread_id == thread_id)
                .order_by(AdvisorMessage.created_at)
            )
        )
        .scalars()
        .all()
    )
    return ThreadOut(
        id=thread.id,
        title=thread.title,
        persona_key=thread.persona_key,
        created_at=thread.created_at,
        messages=[
            MessageOut(
                id=m.id,
                role=m.role,
                text=m.text,
                blocks=m.blocks,
                usage=m.usage,
                created_at=m.created_at,
            )
            for m in messages
        ],
    )


@router.delete("/advisor/threads/{thread_id}", status_code=status.HTTP_204_NO_CONTENT)
async def archive_thread_endpoint(
    thread_id: UUID, user: CurrentUserDep, session: SessionDep
) -> None:
    thread = await session.get(AdvisorThread, thread_id)
    if thread is None:
        raise HTTPException(status_code=404, detail="fil introuvable")
    await _owned_website(session, thread.website_id, user)
    thread.archived_at = datetime.now(UTC)
    await session.commit()


@router.post("/advisor/threads/{thread_id}/messages")
async def post_message_endpoint(
    thread_id: UUID,
    body: PostMessageRequest,
    user: CurrentUserDep,
    session: SessionDep,
    llm: AdvisorLLMDep,
    settings: SettingsDep,
    probe: AuditProbeDep,
    detector: StackDetectorDep,
    tls_checker: TlsCheckerDep,
    gtm_checker: GtmCheckerDep,
    gtm_headless_verifier: GtmHeadlessVerifierDep,
) -> StreamingResponse:
    thread = await session.get(AdvisorThread, thread_id)
    if thread is None:
        raise HTTPException(status_code=404, detail="fil introuvable")
    site = await _owned_website(session, thread.website_id, user)

    today = datetime.now(UTC).date()
    usage = (
        await session.execute(
            select(AdvisorUsage).where(AdvisorUsage.user_id == user.id, AdvisorUsage.day == today)
        )
    ).scalar_one_or_none()
    if usage is not None and usage.message_count >= settings.advisor_daily_message_cap:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Limite quotidienne de messages atteinte ({settings.advisor_daily_message_cap}). "
            "Réessaie demain.",
        )

    async def event_stream():
        try:
            async for event in run_chat_turn(
                session,
                thread=thread,
                website=site,
                user_id=user.id,
                llm=llm,
                user_text=body.text,
                iteration_cap=settings.advisor_tool_iteration_cap,
                probe=probe,
                detector=detector,
                tls_checker=tls_checker,
                gtm_checker=gtm_checker,
                gtm_headless_verifier=gtm_headless_verifier,
            ):
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
            await session.commit()
        except AdvisorMessageCapReached as exc:
            yield f"data: {json.dumps({'kind': 'error', 'text': str(exc)}, ensure_ascii=False)}\n\n"
        except Exception:  # tout echec LLM/reseau en cours de flux -> event d'erreur, pas de crash SSE
            yield (
                'data: {"kind": "error", "text": '
                '"le conseiller a rencontr\\u00e9 un probl\\u00e8me, r\\u00e9essaie"}\n\n'
            )

    return StreamingResponse(event_stream(), media_type="text/event-stream")
