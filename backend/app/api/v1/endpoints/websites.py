"""Gestion des sites suivis : liste, creation (detection + 1er diagnostic),
confirmation de stack, verification SSL a la demande, archivage / purge."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict, field_validator
from sqlalchemy import select

from app.api.deps import (
    AuditProbeDep,
    CurrentUserDep,
    GtmCheckerDep,
    LiveStackDetectorDep,
    SessionDep,
    TlsCheckerDep,
)
from app.models.audit_snapshot import AuditSnapshot
from app.models.enums import StackKind
from app.models.website import Website
from app.models.workspace import Workspace
from app.models.workspace_member import WorkspaceMember
from app.services.audit_engine import apply_tls_status, run_audit
from app.services.stack_detector import StackDetection
from app.services.workspaces import owned_website, user_workspace_ids

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


# --------------------------------------------------------------------------- #
#  Schemas                                                                     #
# --------------------------------------------------------------------------- #


class SslOut(BaseModel):
    status: str | None
    expires_at: datetime | None
    checked_at: datetime | None


class WebsiteOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    domain: str
    display_name: str
    detected_stack: StackKind | None
    stack_label: str | None
    allow_insecure_probe: bool
    ssl_status: str | None
    ssl_expires_at: datetime | None
    ssl_checked_at: datetime | None
    archived_at: datetime | None


class StackGuessOut(BaseModel):
    label: str
    reason: str


class StackDetectionOut(BaseModel):
    stack: StackKind
    confidence: float
    signals: list[str]
    candidates: list[StackGuessOut]
    error: str | None


class IssueDelta(BaseModel):
    created: int
    updated: int
    resolved: int


class CreateWebsiteRequest(BaseModel):
    name: str
    domain: str
    # Sonder malgre une erreur de certificat (choix explicite de l'utilisateur).
    allow_insecure: bool = False

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


class CreateWebsiteResponse(BaseModel):
    id: UUID
    domain: str
    display_name: str
    detected_stack: StackKind | None
    stack_label: str | None
    detection: StackDetectionOut
    ssl: SslOut
    snapshot_id: UUID
    captured_at: datetime
    metrics: dict
    issues: IssueDelta


class SetStackRequest(BaseModel):
    stack_label: str

    @field_validator("stack_label")
    @classmethod
    def _clean(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("stack_label vide")
        return cleaned[:100]


class RedetectRequest(BaseModel):
    allow_insecure: bool = False


class RedetectResponse(BaseModel):
    detected_stack: StackKind | None
    detection: StackDetectionOut


class StackHintResponse(BaseModel):
    detected_stack: StackKind | None
    stack_label: str | None
    confidence: float
    candidates: list[StackGuessOut]
    error: str | None
    # True -> l'UI invite l'utilisateur a confirmer / choisir sa stack.
    needs_confirmation: bool


def _detection_out(detection: StackDetection) -> StackDetectionOut:
    return StackDetectionOut(
        stack=detection.stack,
        confidence=detection.confidence,
        signals=list(detection.signals),
        candidates=[StackGuessOut(label=g.label, reason=g.reason) for g in detection.candidates],
        error=detection.error,
    )


# --------------------------------------------------------------------------- #
#  Endpoints                                                                   #
# --------------------------------------------------------------------------- #


@router.get("/websites", response_model=list[WebsiteOut])
async def list_websites(
    user: CurrentUserDep,
    session: SessionDep,
    include_archived: bool = False,
) -> list[Website]:
    workspace_ids = await user_workspace_ids(session, user.id)
    stmt = select(Website).where(Website.workspace_id.in_(workspace_ids))
    if not include_archived:
        stmt = stmt.where(Website.archived_at.is_(None))
    rows = await session.execute(stmt.order_by(Website.created_at))
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
    tls_checker: TlsCheckerDep,
    gtm_checker: GtmCheckerDep,
) -> CreateWebsiteResponse:
    existing = (
        await session.execute(
            select(Website).where(
                Website.workspace_id.in_(await user_workspace_ids(session, user.id)),
                Website.domain == body.domain,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"le domaine « {body.domain} » est déjà suivi",
        )

    # Meme resolution get-or-create qu'en dev (app/api/v1/endpoints/dev.py).
    # Un utilisateur peut appartenir a plusieurs workspaces (invitations,
    # Task 9) : tri deterministe pour privilegier le workspace dont il est
    # owner (jamais un workspace ou il n'est que membre invite), avec
    # created_at comme depart-egalite stable.
    workspace = (
        await session.execute(
            select(Workspace)
            .join(WorkspaceMember)
            .where(WorkspaceMember.user_id == user.id)
            .order_by((WorkspaceMember.role == "owner").desc(), Workspace.created_at.asc())
        )
    ).scalars().first()
    if workspace is None:
        workspace = Workspace(name=user.display_name or user.email, owner_user_id=user.id)
        session.add(workspace)
        await session.flush()
        session.add(WorkspaceMember(workspace_id=workspace.id, user_id=user.id, role="owner"))
        await session.flush()

    site = Website(
        workspace_id=workspace.id,
        domain=body.domain,
        display_name=body.name,
        allow_insecure_probe=body.allow_insecure,
    )
    session.add(site)
    await session.flush()

    detection: StackDetection = await detector(
        f"https://{body.domain}", allow_insecure=body.allow_insecure
    )

    async def _fixed(_url: str) -> StackDetection:
        return detection

    result = await run_audit(
        session,
        website=site,
        probe=probe,
        user_id=user.id,
        ip_address=request.client.host if request.client else None,
        detector=_fixed,
        tls_checker=tls_checker,
        gtm_checker=gtm_checker,
    )
    await session.commit()

    return CreateWebsiteResponse(
        id=site.id,
        domain=site.domain,
        display_name=site.display_name,
        detected_stack=site.detected_stack,
        stack_label=site.stack_label,
        detection=_detection_out(detection),
        ssl=SslOut(
            status=site.ssl_status,
            expires_at=site.ssl_expires_at,
            checked_at=site.ssl_checked_at,
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


@router.patch("/websites/{website_id}/stack", response_model=WebsiteOut)
async def set_website_stack(
    website_id: UUID, body: SetStackRequest, user: CurrentUserDep, session: SessionDep
) -> Website:
    site = await owned_website(session, website_id=website_id, user_id=user.id)
    site.stack_label = body.stack_label
    await session.commit()
    return site


@router.post("/websites/{website_id}/redetect", response_model=RedetectResponse)
async def redetect_website_stack(
    website_id: UUID,
    body: RedetectRequest,
    user: CurrentUserDep,
    session: SessionDep,
    detector: LiveStackDetectorDep,
) -> RedetectResponse:
    site = await owned_website(session, website_id=website_id, user_id=user.id)
    detection: StackDetection = await detector(
        f"https://{site.domain}", allow_insecure=body.allow_insecure
    )
    site.detected_stack = detection.stack
    site.allow_insecure_probe = body.allow_insecure
    await session.commit()
    return RedetectResponse(detected_stack=site.detected_stack, detection=_detection_out(detection))


@router.get("/websites/{website_id}/stack-hint", response_model=StackHintResponse)
async def website_stack_hint(
    website_id: UUID,
    user: CurrentUserDep,
    session: SessionDep,
    detector: LiveStackDetectorDep,
) -> StackHintResponse:
    site = await owned_website(session, website_id=website_id, user_id=user.id)
    snapshot = (
        await session.execute(
            select(AuditSnapshot)
            .where(AuditSnapshot.website_id == website_id)
            .order_by(AuditSnapshot.captured_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    block = (snapshot.metrics.get("stack_detection") or {}) if snapshot else {}
    confidence = float(block.get("confidence", 0.0))
    error = block.get("error")
    candidates = [
        StackGuessOut(label=item["label"], reason=item["reason"])
        for item in block.get("candidates", [])
    ]

    # Pas d'hypotheses stockees (snapshot anterieur a la v4) -> sonde en direct.
    if not candidates:
        live: StackDetection = await detector(
            f"https://{site.domain}", allow_insecure=site.allow_insecure_probe
        )
        site.detected_stack = live.stack
        confidence = live.confidence
        error = live.error
        candidates = [StackGuessOut(label=g.label, reason=g.reason) for g in live.candidates]
        await session.commit()

    vague = site.detected_stack in (None, StackKind.GENERIC, StackKind.UNKNOWN)
    low_confidence = confidence and confidence < 0.6
    return StackHintResponse(
        detected_stack=site.detected_stack,
        stack_label=site.stack_label,
        confidence=confidence,
        candidates=candidates,
        error=error,
        needs_confirmation=site.stack_label is None and (vague or bool(low_confidence)),
    )


@router.get("/websites/{website_id}/ssl", response_model=SslOut)
async def website_ssl(
    website_id: UUID,
    user: CurrentUserDep,
    session: SessionDep,
    tls_checker: TlsCheckerDep,
) -> SslOut:
    site = await owned_website(session, website_id=website_id, user_id=user.id)
    tls = await tls_checker(site.domain)
    apply_tls_status(site, tls)
    await session.commit()
    return SslOut(status=tls.status, expires_at=tls.expires_at, checked_at=tls.checked_at)


@router.delete("/websites/{website_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_website(
    website_id: UUID,
    user: CurrentUserDep,
    session: SessionDep,
    purge: bool = Query(False, description="Suppression definitive en cascade au lieu d'archiver"),
) -> None:
    site = await owned_website(session, website_id=website_id, user_id=user.id)
    if purge:
        await session.delete(site)  # cascade : snapshots, issues, liens Google
    else:
        site.archived_at = datetime.now(UTC)
    await session.commit()
