"""Assemble le contexte du site pour l'agent : un document JSON deterministe.

Volontairement compact : scores + sous-findings cles, pas les gros tableaux
bruts (costly_entities, lcp_assets, sample_urls). L'agent demande le detail
via un outil a l'increment 3 si besoin.
"""

from __future__ import annotations

import json

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_snapshot import AuditSnapshot
from app.models.enums import IssueSeverity, IssueStatus
from app.models.issue_item import IssueItem
from app.models.website import Website

_SEVERITY_RANK: dict[IssueSeverity, int] = {
    IssueSeverity.CRITICAL: 3,
    IssueSeverity.HIGH: 2,
    IssueSeverity.MEDIUM: 1,
    IssueSeverity.LOW: 0,
}
_OPEN = (IssueStatus.TODO, IssueStatus.IN_PROGRESS)
_HISTORY_LIMIT = 8


def _iso(value) -> str | None:
    return value.isoformat() if value is not None else None


def _snapshot_block(snap: AuditSnapshot) -> dict:
    m = snap.metrics or {}
    ga4, gsc, cwv, gtm = m.get("ga4", {}), m.get("gsc", {}), m.get("cwv", {}), m.get("gtm")
    block = {
        "captured_at": _iso(snap.captured_at),
        "scores": {
            "ga4": int(ga4.get("score", 0)),
            "gsc": int(gsc.get("score", 0)),
            "cwv": int(cwv.get("score", 0)),
        },
        "cwv": {
            "lcp_ms": cwv.get("lcp_ms"),
            "inp_ms": cwv.get("inp_ms"),
            "cls": cwv.get("cls"),
            "field_data": cwv.get("field_data"),
        },
        "ga4": {
            "degraded": bool(ga4.get("degraded", False)),
            "purchase_missing_params": list(ga4.get("purchase_missing_params", [])),
            "missing_events": list(ga4.get("missing_events", [])),
        },
        "gsc": {
            "degraded": bool(gsc.get("degraded", False)),
            "valid_pages": gsc.get("valid_pages"),
            "excluded_pages": gsc.get("excluded_pages"),
            "noindex_pages": gsc.get("noindex_pages"),
            "connection_stale_days": gsc.get("connection_stale_days"),
        },
        "gtm": None,
    }
    if gtm:
        block["gtm"] = {
            "containers": list(gtm.get("containers", [])),
            "snippet_form": gtm.get("snippet_form"),
            "consent_platform": gtm.get("consent_platform"),
            "findings": [
                {"code": f["code"], "severity": f["severity"], "title": f["title"]}
                for f in gtm.get("findings", [])
            ],
        }
    return block


async def build_context(session: AsyncSession, website: Website) -> str:
    snapshots = list(
        (
            await session.execute(
                select(AuditSnapshot)
                .where(AuditSnapshot.website_id == website.id)
                .order_by(AuditSnapshot.captured_at.desc())
                .limit(_HISTORY_LIMIT)
            )
        )
        .scalars()
        .all()
    )
    latest = snapshots[0] if snapshots else None

    issues = list(
        (
            await session.execute(
                select(IssueItem).where(
                    IssueItem.website_id == website.id,
                    IssueItem.status.in_(_OPEN),
                )
            )
        )
        .scalars()
        .all()
    )
    issues.sort(key=lambda i: (_SEVERITY_RANK[i.severity], i.detected_at), reverse=True)

    data_gaps: list[str] = []
    if latest is None:
        data_gaps.append("no_snapshot")
    else:
        lm = latest.metrics or {}
        if lm.get("ga4", {}).get("degraded") or int(lm.get("ga4", {}).get("score", 0)) == 0:
            data_gaps.append("ga4_disconnected")
        if lm.get("gsc", {}).get("degraded") or int(lm.get("gsc", {}).get("score", 0)) == 0:
            data_gaps.append("gsc_disconnected")

    payload = {
        "site": {
            "domain": website.domain,
            "display_name": website.display_name,
            "detected_stack": website.detected_stack.value if website.detected_stack else None,
            "stack_label": website.stack_label,
            "ssl_status": website.ssl_status,
            "ssl_expires_at": _iso(website.ssl_expires_at),
        },
        "latest_snapshot": _snapshot_block(latest) if latest else None,
        "open_issues": [
            {
                "title": i.title,
                "category": i.category.value,
                "severity": i.severity.value,
                "status": i.status.value,
                "detected_at": _iso(i.detected_at),
            }
            for i in issues
        ],
        "score_history": [
            {
                "date": s.captured_at.date().isoformat(),
                "ga4": int((s.metrics or {}).get("ga4", {}).get("score", 0)),
                "gsc": int((s.metrics or {}).get("gsc", {}).get("score", 0)),
                "cwv": int((s.metrics or {}).get("cwv", {}).get("score", 0)),
            }
            for s in reversed(snapshots)
        ],
        "data_gaps": data_gaps,
    }
    return json.dumps(payload, sort_keys=True, ensure_ascii=False, indent=2)
