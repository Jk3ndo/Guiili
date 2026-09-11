"""Outils de lecture exposes a l'agent conseiller pendant le tchat.

Aucun outil n'ecrit quoi que ce soit. `get_page_html` est verrouille au domaine
du site audite (anti-exfiltration / anti-SSRF) : voir `_get_page_html`.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_snapshot import AuditSnapshot
from app.models.website import Website

_MAX_DAYS = 90
_MAX_HTML_BYTES = 40_000
_MAX_REDIRECTS = 5

_PRIVATE_HOST_RE = re.compile(
    r"^(127\.|10\.|192\.168\.|169\.254\.|0\.0\.0\.0$|localhost$|\[?::1\]?$)", re.IGNORECASE
)

TOOL_DEFS: list[dict[str, Any]] = [
    {
        "name": "get_score_history",
        "description": (
            "Historique des scores GA4, Search Console et Core Web Vitals du site "
            "sur les N derniers jours (defaut 30, max 90)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"days": {"type": "integer", "description": "Nombre de jours, 1 a 90."}},
        },
    },
    {
        "name": "get_snapshot_detail",
        "description": "Detail complet (metriques brutes) du dernier scan, ou d'un scan precis par id.",
        "input_schema": {
            "type": "object",
            "properties": {
                "snapshot_id": {
                    "type": "string",
                    "description": "UUID d'un snapshot. Omis = le plus recent.",
                }
            },
        },
    },
    {
        "name": "get_page_html",
        "description": (
            "Recupere le HTML d'une page du site audite. Verrouille au domaine du "
            "site : impossible de recuperer une autre page qu'une page de ce site."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"path": {"type": "string", "description": "Chemin relatif, ex: /tarifs"}},
            "required": ["path"],
        },
    },
    {
        "name": "get_gtm_check",
        "description": (
            "Resultat du diagnostic Google Tag Manager du dernier scan (conteneurs, "
            "CSP, consentement, findings)."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
]


async def _get_score_history(session: AsyncSession, website: Website, days: object) -> dict:
    try:
        n = max(1, min(int(days), _MAX_DAYS))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        n = 30
    since = datetime.now(UTC) - timedelta(days=n)
    rows = (
        await session.execute(
            select(AuditSnapshot)
            .where(AuditSnapshot.website_id == website.id, AuditSnapshot.captured_at >= since)
            .order_by(AuditSnapshot.captured_at)
        )
    ).scalars().all()
    return {
        "history": [
            {
                "date": r.captured_at.date().isoformat(),
                "ga4": int((r.metrics or {}).get("ga4", {}).get("score", 0)),
                "gsc": int((r.metrics or {}).get("gsc", {}).get("score", 0)),
                "cwv": int((r.metrics or {}).get("cwv", {}).get("score", 0)),
            }
            for r in rows
        ]
    }


async def _get_snapshot_detail(session: AsyncSession, website: Website, snapshot_id: object) -> dict:
    stmt = select(AuditSnapshot).where(AuditSnapshot.website_id == website.id)
    if snapshot_id:
        try:
            sid = UUID(str(snapshot_id))
        except ValueError:
            return {"error": "snapshot_id invalide"}
        stmt = stmt.where(AuditSnapshot.id == sid)
    else:
        stmt = stmt.order_by(AuditSnapshot.captured_at.desc()).limit(1)
    row = (await session.execute(stmt)).scalars().first()
    if row is None:
        return {"error": "snapshot introuvable"}
    return {"captured_at": row.captured_at.isoformat(), "metrics": row.metrics}


async def _get_gtm_check(session: AsyncSession, website: Website) -> dict:
    row = (
        await session.execute(
            select(AuditSnapshot)
            .where(AuditSnapshot.website_id == website.id)
            .order_by(AuditSnapshot.captured_at.desc())
            .limit(1)
        )
    ).scalars().first()
    gtm = (row.metrics or {}).get("gtm") if row else None
    if not gtm:
        return {"error": "aucun check GTM disponible"}
    return gtm


def _same_site(host: str, root: str) -> bool:
    host, root = host.lower().rstrip("."), root.lower().rstrip(".")
    return host == root or host.endswith("." + root)


async def _get_page_html(
    website: Website, path: str, *, client: httpx.AsyncClient | None = None
) -> dict:
    if not path.startswith("/"):
        path = "/" + path
    root = website.domain
    url = f"https://{root}{path}"
    owns_client = client is None
    http = client or httpx.AsyncClient(
        follow_redirects=False, timeout=8.0, headers={"User-Agent": "ControlCenterBot/1.0"}
    )
    try:
        for _ in range(_MAX_REDIRECTS):
            try:
                response = await http.get(url)
            except httpx.HTTPError:
                return {"error": "fetch_error"}
            if response.status_code in (301, 302, 303, 307, 308):
                location = response.headers.get("location", "")
                next_url = httpx.URL(url).join(location)
                host = next_url.host or ""
                if _PRIVATE_HOST_RE.match(host) or not _same_site(host, root):
                    return {"error": "redirect_off_domain"}
                url = str(next_url)
                continue
            return {
                "status": response.status_code,
                "final_url": url,
                "html": response.text[:_MAX_HTML_BYTES],
            }
        return {"error": "too_many_redirects"}
    finally:
        if owns_client:
            await http.aclose()


async def dispatch(
    name: str, tool_input: dict, *, session: AsyncSession | None, website: Website
) -> dict:
    if name == "get_score_history":
        return await _get_score_history(session, website, tool_input.get("days", 30))
    if name == "get_snapshot_detail":
        return await _get_snapshot_detail(session, website, tool_input.get("snapshot_id"))
    if name == "get_page_html":
        return await _get_page_html(website, str(tool_input.get("path", "/")))
    if name == "get_gtm_check":
        return await _get_gtm_check(session, website)
    return {"error": f"outil inconnu : {name}"}
