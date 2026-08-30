from __future__ import annotations

import hashlib
import json
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Response, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUserDep, SessionDep
from app.models.audit_log import AuditLog
from app.models.enums import AuditResult, ResourceType, StackKind
from app.models.user import User
from app.models.website import Website
from app.models.website_google_link import WebsiteGoogleLink
from app.services.gtm_generator import build_gtm_container
from app.services.snippet_library import SnippetEvent, get_snippets

router = APIRouter(tags=["gtm"])


async def _owned_website(session: AsyncSession, website_id: UUID, user: User) -> Website:
    site = await session.get(Website, website_id)
    if site is None or site.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="site introuvable")
    return site


@router.get("/websites/{website_id}/gtm-export")
async def gtm_export(
    website_id: UUID,
    user: CurrentUserDep,
    session: SessionDep,
    mode: Literal["merge", "overwrite"] = "merge",
) -> Response:
    site = await _owned_website(session, website_id, user)

    ga4_link = (
        await session.execute(
            select(WebsiteGoogleLink).where(
                WebsiteGoogleLink.website_id == website_id,
                WebsiteGoogleLink.resource_type == ResourceType.GA4_PROPERTY,
            )
        )
    ).scalar_one_or_none()

    container = build_gtm_container(
        domain=site.domain,
        stack=site.detected_stack or StackKind.UNKNOWN,
        ga4_property=ga4_link.resource_id if ga4_link else None,
        import_mode=mode,
    )
    body = json.dumps(container, ensure_ascii=False, indent=2)
    payload_hash = hashlib.sha256(body.encode("utf-8")).hexdigest()

    session.add(
        AuditLog(
            user_id=user.id,
            action="gtm.container_exported",
            resource_type="website",
            resource_id=str(website_id),
            request_payload_hash=payload_hash,
            result=AuditResult.SUCCESS,
        )
    )
    await session.commit()

    filename = f"gtm-container-{site.domain}.json"
    return Response(
        content=body,
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


class SnippetEntryOut(BaseModel):
    stack: StackKind
    event: SnippetEvent
    language: str
    code: str
    target_path: str
    instructions: str


class SnippetsResponse(BaseModel):
    detected_stack: StackKind | None
    resolved_stack: StackKind
    entries: list[SnippetEntryOut]


@router.get("/websites/{website_id}/snippets", response_model=SnippetsResponse)
async def website_snippets(
    website_id: UUID,
    user: CurrentUserDep,
    session: SessionDep,
    event: SnippetEvent | None = None,
) -> SnippetsResponse:
    site = await _owned_website(session, website_id, user)
    entries = get_snippets(site.detected_stack, event)
    return SnippetsResponse(
        detected_stack=site.detected_stack,
        resolved_stack=entries[0].stack,
        entries=[
            SnippetEntryOut(
                stack=entry.stack,
                event=entry.event,
                language=entry.language,
                code=entry.code,
                target_path=entry.target_path,
                instructions=entry.instructions,
            )
            for entry in entries
        ],
    )
