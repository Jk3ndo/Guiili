from __future__ import annotations

import re
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
#  GET /websites/{id}/audit  — diagnostics détaillés (contrat frontend)        #
# --------------------------------------------------------------------------- #


class CwvEntityOut(BaseModel):
    name: str
    category: str
    main_thread_ms: int
    blocking_ms: int


class CwvAssetOut(BaseModel):
    name: str
    current_format: str
    size_kb: int
    estimated_saving_kb: int


class CwvShiftElementOut(BaseModel):
    selector: str
    impact: float
    note: str


class CwvDiagnosticOut(BaseModel):
    metric: str  # "lcp" | "inp" | "cls"
    source: str  # "field" (CrUX) | "lab" (Lighthouse)
    total_blocking_time_ms: int | None = None
    js_execution_ms: int | None = None
    entities: list[CwvEntityOut] | None = None
    element_snippet: str | None = None
    assets: list[CwvAssetOut] | None = None
    preload_hint: str | None = None
    shift_elements: list[CwvShiftElementOut] | None = None
    recommendations: list[str]


class AuditVitalOut(BaseModel):
    id: str
    label: str
    value: str
    raw: float
    rating: str
    target: str
    thresholds: list[float]
    hint: str
    diagnostic: CwvDiagnosticOut | None


class AuditGa4EventOut(BaseModel):
    name: str
    conformity: str  # "conforme" | "partial" | "missing"
    note: str
    volume: int


class AuditGa4Out(BaseModel):
    score: int
    status: str
    status_line: str
    property: str | None
    events: list[AuditGa4EventOut]


class AuditIndexReasonOut(BaseModel):
    label: str
    urls: int


class AuditIndexOut(BaseModel):
    property: str | None
    valid: int
    excluded: int
    reasons: list[AuditIndexReasonOut]


class AuditUrlOut(BaseModel):
    url: str
    status: str
    clicks: int
    impressions: int
    ctr: float
    marketing_action: str


class AuditResponse(BaseModel):
    site_name: str
    domain: str
    captured_at: datetime | None
    ga4: AuditGa4Out
    index: AuditIndexOut
    urls: list[AuditUrlOut]
    vitals: list[AuditVitalOut]


_VITAL_META: dict[str, tuple[str, str, tuple[float, float], str]] = {
    "lcp": ("Largest Contentful Paint", "< 2,5 s", (2500.0, 4000.0), "s"),
    "inp": ("Interaction to Next Paint", "< 200 ms", (200.0, 500.0), "ms"),
    "cls": ("Cumulative Layout Shift", "< 0,1", (0.1, 0.25), ""),
}

_VITAL_RECS: dict[str, list[str]] = {
    "inp": [
        "Differer le chargement des balises tierces (GTM, chat, replay) apres le premier rendu.",
        "Decouper les longues taches JavaScript (> 50 ms) et deplacer les calculs lourds "
        "dans un web worker.",
        "Charger les scripts non critiques sur interaction plutot qu'au chargement.",
    ],
    "lcp": [
        "Servir l'image LCP en AVIF (repli WebP) et la dimensionner a la taille "
        "d'affichage reelle.",
        'Precharger l\'element LCP avec <link rel="preload" ... fetchpriority="high">.',
        "Reduire la chaine de requetes critiques (police + CSS) qui retarde l'affichage.",
    ],
    "cls": [
        "Fixer width / height (ou aspect-ratio) sur les images et media au-dessus de "
        "la ligne de flottaison.",
        "Reserver l'espace des bannieres et encarts injectes apres le chargement.",
    ],
}


def _rating(raw: float, thresholds: tuple[float, float]) -> str:
    good, poor = thresholds
    if raw <= good:
        return "good"
    if raw <= poor:
        return "warn"
    return "bad"


def _format_vital(raw: float, unit: str) -> str:
    if unit == "s":
        return f"{raw / 1000:.1f}".replace(".", ",") + " s"
    if unit == "ms":
        return f"{round(raw)} ms"
    return f"{raw:.2f}".replace(".", ",")


_RATING_HINT = {
    "good": "Signal dans la zone « bon ».",
    "warn": "Signal a ameliorer, proche du seuil.",
    "bad": "Signal hors seuil, impact utilisateur mesurable.",
}


def _preload_hint(snippet: str | None) -> str | None:
    if not snippet or "<img" not in snippet:
        return None
    match = re.search(r'src="([^"]+)"', snippet)
    if not match:
        return None
    return f'<link rel="preload" as="image" href="{match.group(1)}" fetchpriority="high">'


def _build_vitals(cwv: dict) -> list[AuditVitalOut]:
    source = "field" if cwv.get("field_data") else "lab"
    raw_values: dict[str, float] = {
        "lcp": float(cwv.get("lcp_ms", 0) or 0),
        "inp": float(cwv.get("inp_ms", 0) or 0),
        "cls": float(cwv.get("cls", 0) or 0),
    }
    out: list[AuditVitalOut] = []
    for metric, raw in raw_values.items():
        label, target, thresholds, unit = _VITAL_META[metric]
        rating = _rating(raw, thresholds)
        diagnostic: CwvDiagnosticOut | None = None
        if raw > 0:
            diagnostic = _build_diagnostic(metric, source, cwv)
        out.append(
            AuditVitalOut(
                id=metric,
                label=label,
                value=_format_vital(raw, unit),
                raw=raw,
                rating=rating,
                target=target,
                thresholds=list(thresholds),
                hint=_RATING_HINT[rating],
                diagnostic=diagnostic,
            )
        )
    return out


def _build_diagnostic(metric: str, source: str, cwv: dict) -> CwvDiagnosticOut:
    recommendations = _VITAL_RECS[metric]
    if metric == "inp":
        entities = [
            CwvEntityOut(
                name=item["name"],
                category=item["category"],
                main_thread_ms=item["main_thread_ms"],
                blocking_ms=item["blocking_ms"],
            )
            for item in cwv.get("costly_entities", [])
        ]
        return CwvDiagnosticOut(
            metric=metric,
            source=source,
            total_blocking_time_ms=int(cwv.get("total_blocking_time_ms", 0) or 0),
            js_execution_ms=int(cwv.get("js_execution_ms", 0) or 0),
            entities=entities or None,
            recommendations=recommendations,
        )
    if metric == "lcp":
        assets = [
            CwvAssetOut(
                name=item["name"],
                current_format=item["current_format"],
                size_kb=item["size_kb"],
                estimated_saving_kb=item["estimated_saving_kb"],
            )
            for item in cwv.get("lcp_assets", [])
        ]
        snippet = cwv.get("lcp_element")
        return CwvDiagnosticOut(
            metric=metric,
            source=source,
            element_snippet=snippet,
            assets=assets or None,
            preload_hint=_preload_hint(snippet),
            recommendations=recommendations,
        )
    shift_elements = [
        CwvShiftElementOut(selector=item["selector"], impact=item["impact"], note=item["note"])
        for item in cwv.get("shift_elements", [])
    ]
    return CwvDiagnosticOut(
        metric=metric,
        source=source,
        shift_elements=shift_elements or None,
        recommendations=recommendations,
    )


def _build_ga4(ga4: dict) -> AuditGa4Out:
    score = int(ga4.get("score", 0))
    events: list[AuditGa4EventOut] = []
    missing_params = ga4.get("purchase_missing_params") or []
    if missing_params:
        events.append(
            AuditGa4EventOut(
                name="purchase",
                conformity="missing",
                note="Parametres manquants : " + ", ".join(missing_params),
                volume=0,
            )
        )
    for event_name in ga4.get("missing_events") or []:
        events.append(
            AuditGa4EventOut(
                name=event_name,
                conformity="missing",
                note="Evenement jamais recu — action non instrumentee.",
                volume=0,
            )
        )
    if ga4.get("login_missing_user_id"):
        events.append(
            AuditGa4EventOut(
                name="login",
                conformity="partial",
                note="Parametre manquant : user_id (rapprochement cross-device inoperant).",
                volume=0,
            )
        )
    status_line = "Flux actif" if score > 0 else "Flux GA4 non relie (integration P3)"
    return AuditGa4Out(
        score=score,
        status=str(ga4.get("status", "bad")),
        status_line=status_line,
        property=None,
        events=events,
    )


_LOW_CTR = 1.5  # %


def _url_marketing_action(status: str, clicks: int, impressions: int, ctr: float) -> str:
    if status == "Exclue noindex":
        return (
            "Retirer la balise noindex si la page doit ranker, sinon la sortir "
            "du sitemap pour ne plus gaspiller de budget de crawl."
        )
    if status == "Redirection 301":
        return (
            "Mettre a jour les liens internes et externes pointant vers l'ancienne "
            "URL pour transmettre le signal directement a la cible."
        )
    if status == "Découverte non indexée":
        return (
            "Ajouter 3 a 5 liens internes depuis des pages fortes (accueil, articles "
            "phares) et soumettre l'URL a l'inspection pour declencher l'indexation."
        )
    # Indexée
    if impressions >= 500 and ctr < _LOW_CTR:
        return (
            f"Reecrire le Title et la meta-description autour du mot-cle principal : "
            f"CTR {ctr:.1f} % tres en dessous du potentiel (< {_LOW_CTR:.1f} %)."
        )
    if clicks < 20 and impressions < 300:
        return (
            "Renforcer le maillage interne : viser au moins 3 liens contextualises "
            "depuis les articles a fort trafic pour faire remonter la page."
        )
    return (
        "Page performante : construire un cluster de contenu autour du sujet et lier "
        "cette page en pilier pour capter les requetes voisines."
    )


def _build_urls(gsc: dict) -> list[AuditUrlOut]:
    out: list[AuditUrlOut] = []
    for sample in gsc.get("sample_urls", []):
        clicks = int(sample.get("clicks", 0))
        impressions = int(sample.get("impressions", 0))
        ctr = round(clicks / impressions * 100, 1) if impressions else 0.0
        status = str(sample.get("status", "Indexée"))
        out.append(
            AuditUrlOut(
                url=str(sample.get("path", "/")),
                status=status,
                clicks=clicks,
                impressions=impressions,
                ctr=ctr,
                marketing_action=_url_marketing_action(status, clicks, impressions, ctr),
            )
        )
    return out


def _build_index(gsc: dict) -> AuditIndexOut:
    valid = int(gsc.get("valid_pages", 0))
    excluded = int(gsc.get("excluded_pages", 0))
    noindex = int(gsc.get("noindex_pages", 0))
    reasons: list[AuditIndexReasonOut] = []
    if noindex > 0:
        suffix = ", dont des fiches produit" if gsc.get("noindex_on_products") else ""
        reasons.append(
            AuditIndexReasonOut(label=f"Exclue par la balise « noindex »{suffix}", urls=noindex)
        )
    rest = max(0, excluded - noindex)
    if rest > 0:
        reasons.append(AuditIndexReasonOut(label="Exploree, actuellement non indexee", urls=rest))
    stale = int(gsc.get("connection_stale_days", 0))
    if stale >= 3:
        reasons.append(
            AuditIndexReasonOut(label=f"Donnees d'indexation absentes depuis {stale} jours", urls=0)
        )
    return AuditIndexOut(property=None, valid=valid, excluded=excluded, reasons=reasons)


@router.get("/websites/{website_id}/audit", response_model=AuditResponse)
async def website_audit(
    website_id: UUID, user: CurrentUserDep, session: SessionDep
) -> AuditResponse:
    site = await _owned_website(session, website_id, user)

    snapshot = (
        await session.execute(
            select(AuditSnapshot)
            .where(AuditSnapshot.website_id == website_id)
            .order_by(AuditSnapshot.captured_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if snapshot is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="aucun audit disponible")

    metrics = snapshot.metrics
    return AuditResponse(
        site_name=site.display_name,
        domain=site.domain,
        captured_at=snapshot.captured_at,
        ga4=_build_ga4(metrics.get("ga4", {})),
        index=_build_index(metrics.get("gsc", {})),
        urls=_build_urls(metrics.get("gsc", {})),
        vitals=_build_vitals(metrics.get("cwv", {})),
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
        raise HTTPException(status_code=422, detail=f"statut inconnu : {body.status}")
    issue.status = target
    issue.resolved_at = (
        datetime.now(UTC) if target in (IssueStatus.FIXED, IssueStatus.DISMISSED) else None
    )
    await session.flush()
    await session.commit()
    return issue
