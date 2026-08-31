"""Gestion des sites suivis par l'utilisateur : liste + creation avec premier
diagnostic immediat (detection de stack reelle + `run_audit` synchrone)."""

from __future__ import annotations

import re
from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, field_validator
from sqlalchemy import select

from app.api.deps import (
    AuditProbeDep,
    CurrentUserDep,
    LiveStackDetectorDep,
    SessionDep,
)
from app.models.enums import StackKind
from app.models.website import Website
from app.services.audit_engine import run_audit
from app.services.stack_detector import StackDetection

router = APIRouter(tags=["websites"])

# nom d'hote : labels alphanumeriques (+ tirets internes) separes par des points,
# TLD de 2+ lettres. Pas de port, pas d'espace, pas de chemin (deja retire).
_HOSTNAME_RE = re.compile(
    r"^(?=.{1,253}$)(?!-)[a-z0-9-]{1,63}(?<!-)(\.(?!-)[a-z0-9-]{1,63}(?<!-))+$"
)


def normalize_domain(raw: str) -> str:
    """`  HTTPS://www.Mon-Site.FR/blog?x=1 ` -> `mon-site.fr`."""
    value = raw.strip().lower()
    value = re.sub(r"^[a-z][a-z0-9+.-]*://", "", value)  # tout schema (http/https/...)
    value = value.split("/", 1)[0]  # coupe chemin + query + fragment
    value = value.split("@", 1)[-1]  # userinfo eventuel
    value = value.split(":", 1)[0]  # port eventuel
    value = value.removeprefix("www.").strip(".")
    return value


class WebsiteOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    domain: str
    display_name: str
    detected_stack: StackKind | None


class CreateWebsiteRequest(BaseModel):
    name: str
    domain: str

    @field_validator("name")
    @classmethod
    def _clean_name(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("le nom du projet est requis")
        return cleaned[:255]

    @field_validator("domain")
    @classmethod
    def _clean_domain(cls, value: str) -> str:
        domain = normalize_domain(value)
        if not _HOSTNAME_RE.match(domain):
            raise ValueError(f"domaine invalide : {value!r}")
        return domain


class StackDetectionOut(BaseModel):
    stack: StackKind
    confidence: float
    signals: list[str]


class IssueDelta(BaseModel):
    created: int
    updated: int
    resolved: int


class CreateWebsiteResponse(BaseModel):
    id: UUID
    domain: str
    display_name: str
    detected_stack: StackKind | None
    detection: StackDetectionOut
    snapshot_id: UUID
    captured_at: datetime
    metrics: dict
    issues: IssueDelta


@router.get("/websites", response_model=list[WebsiteOut])
async def list_websites(user: CurrentUserDep, session: SessionDep) -> list[Website]:
    rows = await session.execute(
        select(Website).where(Website.user_id == user.id).order_by(Website.created_at)
    )
    return list(rows.scalars().all())


@router.post(
    "/websites",
    response_model=CreateWebsiteResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_website(
    body: CreateWebsiteRequest,
    request: Request,
    user: CurrentUserDep,
    session: SessionDep,
    probe: AuditProbeDep,
    detector: LiveStackDetectorDep,
) -> CreateWebsiteResponse:
    existing = (
        await session.execute(
            select(Website).where(Website.user_id == user.id, Website.domain == body.domain)
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"le domaine « {body.domain} » est déjà suivi",
        )

    site = Website(user_id=user.id, domain=body.domain, display_name=body.name)
    session.add(site)
    await session.flush()

    detection: StackDetection = await detector(f"https://{body.domain}")

    async def _fixed(_url: str) -> StackDetection:
        return detection

    result = await run_audit(
        session,
        website=site,
        probe=probe,
        user_id=user.id,
        ip_address=request.client.host if request.client else None,
        detector=_fixed,
    )
    await session.commit()

    return CreateWebsiteResponse(
        id=site.id,
        domain=site.domain,
        display_name=site.display_name,
        detected_stack=site.detected_stack,
        detection=StackDetectionOut(
            stack=detection.stack,
            confidence=detection.confidence,
            signals=list(detection.signals),
        ),
        snapshot_id=result.snapshot.id,
        captured_at=result.snapshot.captured_at,
        metrics=result.metrics,
        issues=IssueDelta(
            created=len(result.created),
            updated=len(result.updated),
            resolved=len(result.resolved),
        ),
    )
