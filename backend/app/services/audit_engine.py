"""Moteur d'audit : detection de stack -> snapshot -> anomalies -> issues.

Les `issue_items` sont dedupliques via `fingerprint` = sha256(website|rule|subject)
et l'unicite `(website_id, fingerprint)` : un re-scan met a jour la ligne
existante au lieu d'en creer une nouvelle. Une anomalie qui disparait fait
passer l'issue a `fixed` ; si elle reapparait, l'issue repasse a `todo`.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_log import AuditLog
from app.models.audit_snapshot import AuditSnapshot
from app.models.enums import (
    AuditResult,
    IssueCategory,
    IssueSeverity,
    IssueStatus,
    SnapshotSource,
    StackKind,
)
from app.models.issue_item import IssueItem
from app.models.website import Website
from app.services.audit_probe import AuditProbe, ProbeData
from app.services.stack_detector import StackDetection, detect_stack

Detector = Callable[[str], Awaitable[StackDetection]]


@dataclass(frozen=True, slots=True)
class DetectedAnomaly:
    rule_id: str
    subject: str
    category: IssueCategory
    severity: IssueSeverity
    title: str
    description: str


@dataclass(slots=True)
class AuditRunResult:
    snapshot: AuditSnapshot
    detected_stack: StackKind
    metrics: dict
    created: list[IssueItem] = field(default_factory=list)
    updated: list[IssueItem] = field(default_factory=list)
    resolved: list[IssueItem] = field(default_factory=list)


def _score_status(score: int) -> str:
    if score >= 85:
        return "good"
    if score >= 65:
        return "warn"
    return "bad"


def _cwv_anomaly(
    rule: str, subject: str, severity: IssueSeverity, label: str, value: str, target: str
) -> DetectedAnomaly:
    return DetectedAnomaly(
        rule_id=rule,
        subject=subject,
        category=IssueCategory.CWV,
        severity=severity,
        title=f"{label} au-dessus du seuil ({value})",
        description=(
            f"{label} mesure a {value} sur le terrain, cible < {target}. "
            "Signal Core Web Vitals hors zone « bon »."
        ),
    )


def detect_anomalies(data: ProbeData) -> list[DetectedAnomaly]:
    out: list[DetectedAnomaly] = []
    ga4, gsc, cwv = data.ga4, data.gsc, data.cwv

    if ga4.purchase_missing_params:
        params = ", ".join(ga4.purchase_missing_params)
        out.append(
            DetectedAnomaly(
                "ga4_purchase_params",
                "purchase",
                IssueCategory.ANALYTICS,
                IssueSeverity.CRITICAL,
                "L'evenement purchase GA4 ne transmet pas tous les parametres",
                f"Parametres manquants sur l'evenement purchase : {params}. "
                "Les revenus GA4 sont nuls sur les ventes.",
            )
        )
    for event in ga4.missing_events:
        out.append(
            DetectedAnomaly(
                "ga4_event_missing",
                event,
                IssueCategory.ANALYTICS,
                IssueSeverity.HIGH,
                f"L'evenement {event} n'est jamais recu",
                f"Aucun hit GA4 pour {event} : l'action correspondante n'est pas instrumentee.",
            )
        )
    if ga4.login_missing_user_id:
        out.append(
            DetectedAnomaly(
                "ga4_user_id",
                "login",
                IssueCategory.ANALYTICS,
                IssueSeverity.HIGH,
                "L'identifiant utilisateur n'est pas transmis a GA4",
                "Apres connexion, aucun user_id n'est pousse : le rapprochement "
                "cross-device est inoperant.",
            )
        )

    if gsc.connection_stale_days >= 3:
        out.append(
            DetectedAnomaly(
                "gsc_stale",
                "connection",
                IssueCategory.SEO,
                IssueSeverity.HIGH,
                "La connexion Search Console ne renvoie plus de donnees",
                f"Aucune donnee d'indexation depuis {gsc.connection_stale_days} "
                "jours : le diagnostic SEO tourne en aveugle.",
            )
        )
    elif gsc.noindex_pages > 0:
        severity = IssueSeverity.HIGH if gsc.noindex_on_products else IssueSeverity.MEDIUM
        suffix = ", dont des fiches produit." if gsc.noindex_on_products else "."
        out.append(
            DetectedAnomaly(
                "gsc_noindex",
                "noindex",
                IssueCategory.SEO,
                severity,
                f"{gsc.noindex_pages} pages exclues de l'index par une balise noindex",
                f"Une balise noindex empeche l'indexation de {gsc.noindex_pages} page(s){suffix}",
            )
        )
    else:
        total = gsc.valid_pages + gsc.excluded_pages
        if total > 0 and gsc.valid_pages / total < 0.85:
            out.append(
                DetectedAnomaly(
                    "gsc_coverage",
                    "coverage",
                    IssueCategory.SEO,
                    IssueSeverity.MEDIUM,
                    "Couverture d'indexation sous le seuil",
                    f"{gsc.valid_pages} pages indexees sur {total} connues.",
                )
            )

    source = "terrain" if cwv.field_data else "labo"

    if cwv.lcp_ms > 2500:
        severity = IssueSeverity.CRITICAL if cwv.lcp_ms > 4000 else IssueSeverity.HIGH
        detail = (
            f"LCP mesure a {cwv.lcp_ms} ms ({source}), cible < 2500 ms. "
            "Signal Core Web Vitals hors zone « bon »."
        )
        if cwv.lcp_element:
            detail += f" Element LCP : {cwv.lcp_element}."
        assets = cwv.heavy_assets or cwv.blocking_scripts
        if assets:
            detail += f" Assets lourds a optimiser : {', '.join(assets)}."
        out.append(
            DetectedAnomaly(
                "cwv_lcp",
                "lcp",
                IssueCategory.CWV,
                severity,
                f"LCP au-dessus du seuil ({cwv.lcp_ms} ms)",
                detail,
            )
        )

    if cwv.inp_ms > 200:
        detail = (
            f"INP mesure a {cwv.inp_ms} ms ({source}), cible < 200 ms. "
            "Les interactions repondent trop lentement."
        )
        if cwv.third_party_scripts:
            detail += f" Scripts tiers couteux : {', '.join(cwv.third_party_scripts)}."
        elif cwv.blocking_scripts:
            detail += f" Scripts bloquants : {', '.join(cwv.blocking_scripts)}."
        if cwv.js_execution_ms:
            detail += f" Execution JS totale : {cwv.js_execution_ms} ms."
        out.append(
            DetectedAnomaly(
                "cwv_inp",
                "inp",
                IssueCategory.CWV,
                IssueSeverity.MEDIUM,
                f"INP au-dessus du seuil ({cwv.inp_ms} ms)",
                detail,
            )
        )

    if cwv.cls > 0.1:
        out.append(
            _cwv_anomaly("cwv_cls", "cls", IssueSeverity.MEDIUM, "CLS", f"{cwv.cls:.2f}", "0.1")
        )
    return out


def _fingerprint(website_id: UUID, anomaly: DetectedAnomaly) -> str:
    raw = f"{website_id}|{anomaly.rule_id}|{anomaly.subject}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _build_metrics(detection: StackDetection, data: ProbeData) -> dict:
    ga4, gsc, cwv = data.ga4, data.gsc, data.cwv
    return {
        "stack": detection.stack.value,
        "ga4": {
            "score": ga4.score,
            "status": _score_status(ga4.score),
            "purchase_missing_params": list(ga4.purchase_missing_params),
            "missing_events": list(ga4.missing_events),
            "login_missing_user_id": ga4.login_missing_user_id,
        },
        "gsc": {
            "score": gsc.score,
            "status": _score_status(gsc.score),
            "valid_pages": gsc.valid_pages,
            "excluded_pages": gsc.excluded_pages,
            "noindex_pages": gsc.noindex_pages,
            "noindex_on_products": gsc.noindex_on_products,
            "connection_stale_days": gsc.connection_stale_days,
        },
        "cwv": {
            "score": cwv.score,
            "status": _score_status(cwv.score),
            "lcp_ms": cwv.lcp_ms,
            "inp_ms": cwv.inp_ms,
            "cls": cwv.cls,
            "field_data": cwv.field_data,
            "js_execution_ms": cwv.js_execution_ms,
            "total_blocking_time_ms": cwv.total_blocking_time_ms,
            "lcp_element": cwv.lcp_element,
            "blocking_scripts": list(cwv.blocking_scripts),
            "costly_entities": [asdict(entity) for entity in cwv.costly_entities],
            "lcp_assets": [asdict(asset) for asset in cwv.lcp_assets],
            "shift_elements": [asdict(element) for element in cwv.shift_elements],
        },
    }


async def run_audit(
    session: AsyncSession,
    *,
    website: Website,
    probe: AuditProbe,
    user_id: UUID | None = None,
    ip_address: str | None = None,
    detector: Detector | None = None,
) -> AuditRunResult:
    now = datetime.now(UTC)
    run_detector = detector or detect_stack

    detection = await run_detector(f"https://{website.domain}")
    website.detected_stack = detection.stack

    data = await probe.collect(domain=website.domain, stack=detection.stack)
    metrics = _build_metrics(detection, data)

    snapshot = AuditSnapshot(
        website_id=website.id,
        captured_at=now,
        source=SnapshotSource.COMPOSITE,
        metrics=metrics,
    )
    session.add(snapshot)
    await session.flush()

    anomalies = detect_anomalies(data)
    result = AuditRunResult(snapshot=snapshot, detected_stack=detection.stack, metrics=metrics)

    seen: set[str] = set()
    for anomaly in anomalies:
        fingerprint = _fingerprint(website.id, anomaly)
        seen.add(fingerprint)
        existing = (
            await session.execute(
                select(IssueItem).where(
                    IssueItem.website_id == website.id,
                    IssueItem.fingerprint == fingerprint,
                )
            )
        ).scalar_one_or_none()

        if existing is None:
            item = IssueItem(
                website_id=website.id,
                title=anomaly.title,
                description=anomaly.description,
                category=anomaly.category,
                severity=anomaly.severity,
                status=IssueStatus.TODO,
                fingerprint=fingerprint,
                detected_at=now,
                source_snapshot_id=snapshot.id,
            )
            session.add(item)
            await session.flush()
            result.created.append(item)
            continue

        existing.title = anomaly.title
        existing.description = anomaly.description
        existing.category = anomaly.category
        existing.severity = anomaly.severity
        existing.detected_at = now
        existing.source_snapshot_id = snapshot.id
        if existing.status == IssueStatus.FIXED:
            existing.status = IssueStatus.TODO
            existing.resolved_at = None
        await session.flush()
        result.updated.append(existing)

    # Anomalies disparues -> l'issue (creee par un scan precedent) passe a fixed.
    stale = (
        (
            await session.execute(
                select(IssueItem).where(
                    IssueItem.website_id == website.id,
                    IssueItem.source_snapshot_id.is_not(None),
                    IssueItem.status.in_((IssueStatus.TODO, IssueStatus.IN_PROGRESS)),
                )
            )
        )
        .scalars()
        .all()
    )
    for item in stale:
        if item.fingerprint not in seen:
            item.status = IssueStatus.FIXED
            item.resolved_at = now
            result.resolved.append(item)
    await session.flush()

    payload = {"website_id": str(website.id), "domain": website.domain}
    payload_hash = hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()
    session.add(
        AuditLog(
            user_id=user_id,
            action="website.scan",
            resource_type="website",
            resource_id=str(website.id),
            request_payload_hash=payload_hash,
            result=AuditResult.SUCCESS,
            ip_address=ip_address,
        )
    )
    await session.flush()

    return result
