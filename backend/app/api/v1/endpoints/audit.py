from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    AuditProbeDep,
    CurrentUserDep,
    SessionDep,
    StackDetectorDep,
)
from app.models.audit_log import AuditLog
from app.models.audit_snapshot import AuditSnapshot
from app.models.enums import (
    IssueCategory,
    IssueSeverity,
    IssueStatus,
    StackKind,
)
from app.models.issue_item import IssueItem
from app.models.user import User
from app.models.website import Website
from app.services.audit_engine import run_audit

router = APIRouter(tags=["audit"])

_SEVERITY_RANK: dict[IssueSeverity, int] = {
    IssueSeverity.CRITICAL: 3,
    IssueSeverity.HIGH: 2,
    IssueSeverity.MEDIUM: 1,
    IssueSeverity.LOW: 0,
}
_OPEN_STATUSES = (IssueStatus.TODO, IssueStatus.IN_PROGRESS)
_METRIC_LABEL = {"ga4": "Santé GA4", "gsc": "Indexation GSC", "cwv": "Core Web Vitals"}


async def _owned_website(session: AsyncSession, website_id: UUID, user: User) -> Website:
    site = await session.get(Website, website_id)
    if site is None or site.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="site introuvable")
    return site


# --------------------------------------------------------------------------- #
#  POST /websites/{id}/scan                                                    #
# --------------------------------------------------------------------------- #


class IssueDelta(BaseModel):
    created: int
    updated: int
    resolved: int


class ScanResponse(BaseModel):
    snapshot_id: UUID
    detected_stack: StackKind
    metrics: dict
    issues: IssueDelta


@router.post(
    "/websites/{website_id}/scan",
    response_model=ScanResponse,
    status_code=status.HTTP_201_CREATED,
)
async def scan_website(
    website_id: UUID,
    request: Request,
    user: CurrentUserDep,
    session: SessionDep,
    probe: AuditProbeDep,
    detector: StackDetectorDep,
) -> ScanResponse:
    site = await _owned_website(session, website_id, user)
    result = await run_audit(
        session,
        website=site,
        probe=probe,
        user_id=user.id,
        ip_address=request.client.host if request.client else None,
        detector=detector,
    )
    await session.commit()
    return ScanResponse(
        snapshot_id=result.snapshot.id,
        detected_stack=result.detected_stack,
        metrics=result.metrics,
        issues=IssueDelta(
            created=len(result.created),
            updated=len(result.updated),
            resolved=len(result.resolved),
        ),
    )


# --------------------------------------------------------------------------- #
#  GET /websites/{id}/overview                                                 #
# --------------------------------------------------------------------------- #


class OverviewMetric(BaseModel):
    id: str
    label: str
    value: str
    score: int
    status: str


class OverviewRecommendation(BaseModel):
    severity: str
    title: str
    detail: str
    cta_kind: str


class OverviewEvent(BaseModel):
    id: UUID
    kind: str
    action: str
    target: str
    result: str
    hours_ago: int


class OverviewResponse(BaseModel):
    site_name: str
    domain: str
    stack: StackKind | None
    last_scan_hours_ago: int | None
    metrics: list[OverviewMetric]
    recommendation: OverviewRecommendation | None
    events: list[OverviewEvent]


def _hours_since(moment: datetime) -> int:
    delta = datetime.now(UTC) - moment
    return max(0, int(delta.total_seconds() // 3600))


@router.get("/websites/{website_id}/overview", response_model=OverviewResponse)
async def website_overview(
    website_id: UUID, user: CurrentUserDep, session: SessionDep
) -> OverviewResponse:
    site = await _owned_website(session, website_id, user)

    snapshot = (
        await session.execute(
            select(AuditSnapshot)
            .where(AuditSnapshot.website_id == website_id)
            .order_by(AuditSnapshot.captured_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    metrics: list[OverviewMetric] = []
    if snapshot is not None:
        for key in ("ga4", "gsc", "cwv"):
            block = snapshot.metrics.get(key, {})
            score = int(block.get("score", 0))
            metrics.append(
                OverviewMetric(
                    id=key,
                    label=_METRIC_LABEL[key],
                    value="—" if score == 0 else str(score),
                    score=score,
                    status=str(block.get("status", "bad")),
                )
            )

    top_issue = (
        (
            await session.execute(
                select(IssueItem).where(
                    IssueItem.website_id == website_id,
                    IssueItem.status.in_(_OPEN_STATUSES),
                )
            )
        )
        .scalars()
        .all()
    )
    recommendation = None
    if top_issue:
        chosen = max(
            top_issue,
            key=lambda i: (_SEVERITY_RANK[i.severity], i.detected_at),
        )
        recommendation = OverviewRecommendation(
            severity="high"
            if chosen.severity in (IssueSeverity.CRITICAL, IssueSeverity.HIGH)
            else "medium",
            title=chosen.title,
            detail=chosen.description,
            cta_kind="gtm"
            if chosen.category in (IssueCategory.ANALYTICS, IssueCategory.TRACKING)
            else "snippet",
        )

    logs = (
        (
            await session.execute(
                select(AuditLog)
                .where(AuditLog.resource_id == str(website_id))
                .order_by(AuditLog.created_at.desc())
                .limit(5)
            )
        )
        .scalars()
        .all()
    )
    events = [
        OverviewEvent(
            id=log.id,
            kind="scan",
            action="Diagnostic complet exécuté",
            target=site.domain,
            result=log.result.value,
            hours_ago=_hours_since(log.created_at),
        )
        for log in logs
    ]

    return OverviewResponse(
        site_name=site.display_name,
        domain=site.domain,
        stack=site.detected_stack,
        last_scan_hours_ago=(_hours_since(snapshot.captured_at) if snapshot else None),
        metrics=metrics,
        recommendation=recommendation,
        events=events,
    )


# --------------------------------------------------------------------------- #
#  GET /websites/{id}/issues  &  PATCH .../{issue_id}                          #
# --------------------------------------------------------------------------- #


class IssueOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    title: str
    description: str
    category: IssueCategory
    severity: IssueSeverity
    status: IssueStatus
    fingerprint: str
    detected_at: datetime
    resolved_at: datetime | None


@router.get("/websites/{website_id}/issues", response_model=list[IssueOut])
async def list_website_issues(
    website_id: UUID,
    user: CurrentUserDep,
    session: SessionDep,
    status_filter: Annotated[IssueStatus | None, Query(alias="status")] = None,
    severity: IssueSeverity | None = None,
) -> list[IssueItem]:
    await _owned_website(session, website_id, user)
    stmt = select(IssueItem).where(IssueItem.website_id == website_id)
    if status_filter is not None:
        stmt = stmt.where(IssueItem.status == status_filter)
    if severity is not None:
        stmt = stmt.where(IssueItem.severity == severity)
    stmt = stmt.order_by(IssueItem.detected_at.desc())
    return list((await session.execute(stmt)).scalars().all())


_PATCH_MAP: dict[str, IssueStatus] = {
    "todo": IssueStatus.TODO,
    "in_progress": IssueStatus.IN_PROGRESS,
    "resolved": IssueStatus.FIXED,
    "fixed": IssueStatus.FIXED,
    "dismissed": IssueStatus.DISMISSED,
}


class IssuePatchRequest(BaseModel):
    status: str


@router.patch("/websites/{website_id}/issues/{issue_id}", response_model=IssueOut)
async def patch_website_issue(
    website_id: UUID,
    issue_id: UUID,
    body: IssuePatchRequest,
    user: CurrentUserDep,
    session: SessionDep,
) -> IssueItem:
    await _owned_website(session, website_id, user)
    issue = await session.get(IssueItem, issue_id)
    if issue is None or issue.website_id != website_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="anomalie introuvable")
    target = _PATCH_MAP.get(body.status.lower())
    if target is None:
        raise HTTPException(
            status_code=422, detail=f"statut inconnu : {body.status}"
        )
    issue.status = target
    issue.resolved_at = (
        datetime.now(UTC) if target in (IssueStatus.FIXED, IssueStatus.DISMISSED) else None
    )
    await session.flush()
    await session.commit()
    return issue
