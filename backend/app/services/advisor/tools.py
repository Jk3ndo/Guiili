"""Outils de lecture exposes a l'agent conseiller pendant le tchat.

Aucun outil n'ecrit quoi que ce soit. `get_page_html` est verrouille au domaine
du site audite (anti-exfiltration / anti-SSRF) : voir `_get_page_html`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.advisor import AdvisorToolCall
from app.models.audit_snapshot import AuditSnapshot
from app.models.website import Website
from app.services.audit_engine import Detector, GtmChecker, TlsChecker, run_audit
from app.services.audit_probe import AuditProbe
from app.services.gtm_headless import GtmHeadlessVerifier, headless_result_to_dict
from app.services.snippet_library import SnippetEvent, get_snippets

_MAX_DAYS = 90
_MAX_HTML_BYTES = 40_000
_MAX_REDIRECTS = 5

_PRIVATE_HOST_RE = re.compile(
    r"^(127\.|10\.|192\.168\.|169\.254\.|0\.0\.0\.0$|localhost$|\[?::1\]?$)", re.IGNORECASE
)

_RATE_LIMITS: dict[str, timedelta] = {
    "trigger_rescan": timedelta(minutes=10),
    "run_gtm_headless_probe": timedelta(minutes=5),
}


@dataclass(frozen=True, slots=True)
class ToolContext:
    """Contexte passe a `dispatch` : donnees + dependances d'action optionnelles.

    Les outils de lecture (increment 3a) n'utilisent que `session`/`website`.
    Les outils d'action (increment 3b) ont besoin en plus de `user_id`,
    `thread_id` (rate-limit) et des sondes reelles (`probe`, `detector`,
    `tls_checker`, `gtm_checker`).
    """

    session: AsyncSession | None
    website: Website
    user_id: UUID | None = None
    thread_id: UUID | None = None
    probe: AuditProbe | None = None
    detector: Detector | None = None
    tls_checker: TlsChecker | None = None
    gtm_checker: GtmChecker | None = None
    gtm_headless_verifier: GtmHeadlessVerifier | None = None

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
    {
        "name": "trigger_rescan",
        "description": (
            "Relance un diagnostic complet du site (stack, SSL, GTM, CWV, GA4/GSC) "
            "et met a jour les issues. Action reelle qui modifie l'etat du site "
            "suivi — a utiliser seulement si la demande de l'utilisateur le justifie."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "run_gtm_headless_probe",
        "description": (
            "Verifie la configuration GTM dans un vrai navigateur (Chromium headless) : "
            "le script gtm.js se charge-t-il reellement, le conteneur s'initialise-t-il, "
            "dataLayer existe-t-il, la CSP bloque-t-elle effectivement googletagmanager.com. "
            "Confirme ou infirme le check statique. Necessite qu'un diagnostic complet ait "
            "deja ete lance sur ce site."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "draft_gtm_snippet",
        "description": (
            "Genere un extrait de code dataLayer.push pour un evenement de "
            "conversion (purchase, lead, custom), adapte a la stack detectee du site."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "event": {"type": "string", "enum": ["purchase", "lead", "custom"]},
            },
            "required": ["event"],
        },
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


async def _rate_limited(session: AsyncSession, *, thread_id: UUID, tool: str) -> bool:
    """True si l'outil a deja ete appele dans la fenetre — l'appel doit etre refuse."""
    since = datetime.now(UTC) - _RATE_LIMITS[tool]
    recent = (
        await session.execute(
            select(AdvisorToolCall.id).where(
                AdvisorToolCall.thread_id == thread_id,
                AdvisorToolCall.tool == tool,
                AdvisorToolCall.called_at >= since,
            )
        )
    ).scalar_one_or_none()
    return recent is not None


async def _record_tool_call(session: AsyncSession, *, thread_id: UUID, tool: str) -> None:
    session.add(AdvisorToolCall(thread_id=thread_id, tool=tool, called_at=datetime.now(UTC)))
    await session.flush()


async def _trigger_rescan(ctx: ToolContext) -> dict:
    if ctx.session is None or ctx.thread_id is None:
        return {"error": "contexte insuffisant pour relancer un diagnostic"}
    if not (ctx.probe and ctx.detector and ctx.tls_checker):
        return {"error": "relance de diagnostic indisponible dans ce contexte"}
    if await _rate_limited(ctx.session, thread_id=ctx.thread_id, tool="trigger_rescan"):
        return {"error": "diagnostic deja relance recemment sur ce fil, reessaie plus tard"}

    result = await run_audit(
        ctx.session,
        website=ctx.website,
        probe=ctx.probe,
        user_id=ctx.user_id,
        detector=ctx.detector,
        tls_checker=ctx.tls_checker,
        gtm_checker=ctx.gtm_checker,
    )
    await _record_tool_call(ctx.session, thread_id=ctx.thread_id, tool="trigger_rescan")
    return {
        "snapshot_id": str(result.snapshot.id),
        "detected_stack": result.detected_stack.value,
        "issues_created": len(result.created),
        "issues_updated": len(result.updated),
        "issues_resolved": len(result.resolved),
    }


async def _run_gtm_headless_probe(ctx: ToolContext) -> dict:
    if ctx.session is None or ctx.thread_id is None:
        return {"error": "contexte insuffisant pour la verification headless"}
    if ctx.gtm_headless_verifier is None:
        return {"error": "verification headless indisponible dans ce contexte"}
    if await _rate_limited(ctx.session, thread_id=ctx.thread_id, tool="run_gtm_headless_probe"):
        return {"error": "verification headless deja lancee recemment sur ce fil, reessaie plus tard"}

    row = (
        await ctx.session.execute(
            select(AuditSnapshot)
            .where(AuditSnapshot.website_id == ctx.website.id)
            .order_by(AuditSnapshot.captured_at.desc())
            .limit(1)
        )
    ).scalars().first()
    if row is None or not row.metrics.get("gtm"):
        return {"error": "aucun check GTM statique disponible, relance un diagnostic d'abord"}

    result = await ctx.gtm_headless_verifier(f"https://{ctx.website.domain}")
    headless_block = headless_result_to_dict(result)
    row.metrics = {**row.metrics, "gtm": {**row.metrics["gtm"], "headless": headless_block}}
    await _record_tool_call(ctx.session, thread_id=ctx.thread_id, tool="run_gtm_headless_probe")
    return headless_block


async def _draft_gtm_snippet(website: Website, event: str) -> dict:
    try:
        evt = SnippetEvent(event)
    except ValueError:
        options = ", ".join(e.value for e in SnippetEvent)
        return {"error": f"evenement inconnu : {event!r}. Choisir parmi : {options}."}
    entries = get_snippets(website.detected_stack, evt)
    if not entries:
        return {"error": "aucun snippet disponible pour cette stack"}
    entry = entries[0]
    return {
        "language": entry.language,
        "code": entry.code,
        "target_path": entry.target_path,
        "instructions": entry.instructions,
    }


async def dispatch(name: str, tool_input: dict, ctx: ToolContext) -> dict:
    if name == "get_score_history":
        return await _get_score_history(ctx.session, ctx.website, tool_input.get("days", 30))
    if name == "get_snapshot_detail":
        return await _get_snapshot_detail(ctx.session, ctx.website, tool_input.get("snapshot_id"))
    if name == "get_page_html":
        return await _get_page_html(ctx.website, str(tool_input.get("path", "/")))
    if name == "get_gtm_check":
        return await _get_gtm_check(ctx.session, ctx.website)
    if name == "trigger_rescan":
        return await _trigger_rescan(ctx)
    if name == "run_gtm_headless_probe":
        return await _run_gtm_headless_probe(ctx)
    if name == "draft_gtm_snippet":
        return await _draft_gtm_snippet(ctx.website, str(tool_input.get("event", "")))
    return {"error": f"outil inconnu : {name}"}
