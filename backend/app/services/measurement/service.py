# backend/app/services/measurement/service.py
"""Orchestration du plan de mesure : collecte des faits, évaluation du catalogue,
persistance de l'état courant et construction de la vue API."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import ConnectionStatus, ResourceType
from app.models.google_connection import GoogleConnection
from app.models.measurement_item_event import MeasurementItemEvent
from app.models.measurement_item_status import MeasurementItemStatus
from app.models.website import Website
from app.models.website_google_link import WebsiteGoogleLink
from app.models.website_profile import WebsiteProfile
from app.services.gtm_check import analyze_gtm
from app.services.gtm_headless import GtmHeadlessVerifier
from app.services.measurement.catalog import (
    ITEMS,
    LAYER_ORDER,
    is_applicable,
)
from app.services.measurement.checks import Facts, HeadlessFacts, evaluate
from app.services.measurement.event_snippets import snippet_for_event
from app.services.measurement.fetch import PageFetcher
from app.services.measurement.google_reader import GoogleReader, GoogleReadError
from app.services.measurement.site_types import detect_site_types, resolve_effective_types
from app.services.measurement.types import SITE_TYPES, MeasurementItem, Outcome

COOLDOWN = timedelta(minutes=5)
# Au-delà, le dernier résultat du navigateur n'est plus une observation fiable : on
# l'écarte plutôt que de maintenir un « manquant » (ou « présent ») périmé.
HEADLESS_MAX_AGE = timedelta(hours=24)

ReaderFactory = Callable[[AsyncSession, Website], Awaitable[GoogleReader]]

_DEAD_TOKEN_REASONS = frozenset({"ga4_not_connected", "token_unavailable"})


@dataclass(frozen=True, slots=True)
class RefreshResult:
    headless_ran: bool = False
    headless_skipped: bool = False
    headless_error: str | None = None


def clean_confirmed_types(confirmed: list[str] | None) -> list[str] | None:
    """Types confirmés valides et sans doublon, dans l'ordre ; `None` si rien d'exploitable
    (`resolve_effective_types` ne valide rien : liste vide = non confirmé)."""
    if not confirmed:
        return None
    cleaned = [t for t in dict.fromkeys(confirmed) if t in SITE_TYPES]
    return cleaned or None


async def get_or_create_profile(session: AsyncSession, website_id: Any) -> WebsiteProfile:
    profile = await session.get(WebsiteProfile, website_id)
    if profile is None:
        profile = WebsiteProfile(website_id=website_id, detected_types=[], params={})
        session.add(profile)
        await session.flush()
    return profile


def record_state_change(
    session: AsyncSession,
    *,
    website_id: Any,
    item_id: str,
    previous: str | None,
    current: str,
    evidence: dict[str, Any],
    at: datetime,
) -> None:
    """Historise un changement d'état. Ne fait rien si l'état est inchangé, ni pour la
    première observation d'un item « non concerné » (bruit sans information)."""
    if previous == current:
        return
    if previous is None and current == "not_applicable":
        return
    session.add(
        MeasurementItemEvent(
            website_id=website_id,
            item_id=item_id,
            from_state=previous,
            to_state=current,
            at=at,
            evidence=dict(evidence),
        )
    )


async def _safe(call: Callable[[], Awaitable[Any]]) -> tuple[Any, str | None]:
    try:
        return await call(), None
    except GoogleReadError as exc:
        return None, exc.reason


def _robots_ok(robots: Any) -> bool | None:
    """`True` : 200 et contenu non HTML (un repli SPA en `text/html` n'est pas un
    robots.txt). `False` : 404 ou 410 seulement. Sinon `None` (403, 429, 5xx, injoignable,
    HTML) : on ne conclut pas."""
    if robots is None:
        return None
    if robots.status == 200:
        return None if "html" in robots.headers.get("content-type", "").lower() else True
    if robots.status in (404, 410):
        return False
    return None


def _page_facts(page: Any) -> tuple[str | None, str | None]:
    """(html, erreur) à partir d'un `PageSnapshot` ou de `None`."""
    if page is None:
        return None, "fetch_error"
    if page.status >= 400:
        return None, "http_error"
    if "html" not in page.headers.get("content-type", "").lower():
        return None, "non_html"
    return page.html, None


async def refresh_plan(
    session: AsyncSession,
    website: Website,
    *,
    fetcher: PageFetcher,
    reader: GoogleReader,
    verifier: GtmHeadlessVerifier,
    run_headless: bool,
    now: datetime | None = None,
) -> RefreshResult:
    """Recalcule et enregistre l'état de chaque item. Ne fait pas de commit."""
    now = now or datetime.now(UTC)
    # Un rafraîchissement à la fois par site (deux onglets, StrictMode...) : le second
    # attend la fin de la transaction du premier, relit son état (profil créé, délai de
    # 5 minutes du headless, transitions déjà écrites) et n'écrit rien en double. Coût
    # connu : la connexion à la base est tenue pendant toute la collecte (réseau compris).
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:website_id))"),
        {"website_id": str(website.id)},
    )
    profile = await get_or_create_profile(session, website.id)
    confirmed = clean_confirmed_types(profile.confirmed_types)

    base_url = f"https://{website.domain}"
    insecure = website.allow_insecure_probe
    page = await fetcher(base_url, allow_insecure=insecure)
    html, page_error = _page_facts(page)
    gtm = analyze_gtm(page) if html is not None and page is not None else None

    if html is not None and confirmed is None:
        profile.detected_types = detect_site_types(html, website.detected_stack)
    effective = tuple(resolve_effective_types(profile.detected_types, confirmed))

    robots = await fetcher(f"{base_url}/robots.txt", allow_insecure=insecure)
    robots_ok = _robots_ok(robots)

    # -- navigateur headless (action explicite, délai de 5 minutes) ---------------
    headless = HeadlessFacts.from_dict(profile.headless_result)
    kept_at = profile.headless_checked_at
    if headless is not None and (kept_at is None or now - kept_at > HEADLESS_MAX_AGE):
        headless = None
    ran = skipped = False
    error: str | None = None
    if run_headless:
        last = profile.headless_checked_at
        if last is not None and now - last < COOLDOWN:
            skipped = True
        else:
            result = await verifier(base_url)
            if result.error is None:
                headless = HeadlessFacts.from_result(result)
                profile.headless_result = headless.to_dict()
                profile.headless_checked_at = now
                ran = True
            else:
                error = result.error

    # -- lectures Google -------------------------------------------------------
    ga4_stats, ga4_reason = await _safe(reader.event_stats)
    if ga4_reason in _DEAD_TOKEN_REASONS:
        key_events, key_reason = None, ga4_reason
        ads_count, ads_reason = None, ga4_reason
    else:
        key_events, key_reason = await _safe(reader.key_events)
        ads_count, ads_reason = await _safe(reader.ads_links_count)
    sitemaps, sitemaps_reason = await _safe(reader.sitemaps_count)

    # -- état précédent (marquages manuels, items écartés) ----------------------
    existing = {
        row.item_id: row
        for row in (
            await session.execute(
                select(MeasurementItemStatus).where(MeasurementItemStatus.website_id == website.id)
            )
        ).scalars()
    }
    manual_done = frozenset(
        item_id for item_id, row in existing.items() if row.evidence.get("manual_done") is True
    )

    facts = Facts(
        page_html=html,
        page_error=page_error,
        gtm=gtm,
        headless=headless,
        ga4_stats=ga4_stats,
        ga4_reason=ga4_reason,
        key_events=key_events,
        key_events_reason=key_reason,
        ads_links_count=ads_count,
        ads_links_reason=ads_reason,
        gsc_state=reader.gsc_state,
        sitemaps_count=sitemaps,
        sitemaps_reason=sitemaps_reason,
        robots_ok=robots_ok,
        robots_reason=None if robots_ok is not None else "robots_unreadable",
        ssl_status=website.ssl_status,
        effective_types=effective,
        manual_done=manual_done,
    )

    uses_ads = profile.params.get("uses_google_ads")
    for item in ITEMS:
        row = existing.get(item.id)
        if not is_applicable(item, effective, uses_ads):
            # Le marquage manuel survit à un passage en « non concerné ».
            kept = {"manual_done": True} if item.id in manual_done else {}
            outcome = Outcome("not_applicable", kept, None)
        elif row is not None and row.dismissed_at is not None:
            outcome = Outcome("dismissed", dict(row.evidence), None)
        else:
            outcome = evaluate(item, facts)
        record_state_change(
            session,
            website_id=website.id,
            item_id=item.id,
            previous=row.state if row is not None else None,
            current=outcome.state,
            evidence=outcome.evidence,
            at=now,
        )
        if row is None:
            session.add(
                MeasurementItemStatus(
                    website_id=website.id,
                    item_id=item.id,
                    state=outcome.state,
                    evidence=outcome.evidence,
                    reason=outcome.reason,
                    checked_at=now,
                )
            )
        else:
            row.state = outcome.state
            row.evidence = outcome.evidence
            row.reason = outcome.reason
            row.checked_at = now
    await session.flush()
    return RefreshResult(headless_ran=ran, headless_skipped=skipped, headless_error=error)


# ---------------------------------------------------------------------------
#  Vue API
# ---------------------------------------------------------------------------


def _is_done(item: MeasurementItem, state: str) -> bool:
    return state == "received" or (state == "on_page" and item.max_level == "on_page")


def _snippet_dict(item: MeasurementItem, website: Website) -> dict[str, str] | None:
    if "snippet" not in item.actions or not item.snippet_event:
        return None
    snippet = snippet_for_event(item.snippet_event, website.detected_stack)
    if snippet is None:
        return None
    return {
        "language": snippet.language,
        "code": snippet.code,
        "target_path": snippet.target_path,
        "instructions": snippet.instructions,
    }


def _next_action_ids(items: list[dict[str, Any]], *, limit: int = 3) -> list[str]:
    """Les items les plus utiles à faire maintenant.

    D'abord ce qui est prouvé manquant (ou pas encore vérifié), puis le reste à
    confirmer ; à égalité, le poids (majoré pour un gain rapide) puis la couche."""
    candidates = [
        item
        for item in items
        if not item["done"] and item["state"] not in ("not_applicable", "dismissed")
    ]

    def rank(item: dict[str, Any]) -> tuple[int, int, int]:
        tier = 0 if item["state"] in ("missing", "unknown") else 1
        bonus = 25 if item["quick_win"] else 0
        return (tier, -(item["weight"] + bonus), LAYER_ORDER.index(item["layer"]))

    # `items` suit l'ordre du catalogue à couche/poids égaux et `sorted` est stable :
    # les égalités sont départagées de façon déterministe.
    return [item["id"] for item in sorted(candidates, key=rank)[:limit]]


async def build_plan_view(session: AsyncSession, website: Website) -> dict[str, Any]:
    profile = await session.get(WebsiteProfile, website.id)
    detected = list(profile.detected_types) if profile else []
    confirmed = clean_confirmed_types(profile.confirmed_types) if profile else None
    params = dict(profile.params) if profile else {}
    effective = resolve_effective_types(detected, confirmed)

    rows = {
        row.item_id: row
        for row in (
            await session.execute(
                select(MeasurementItemStatus).where(MeasurementItemStatus.website_id == website.id)
            )
        ).scalars()
    }
    linked_types = set(
        (
            await session.execute(
                select(WebsiteGoogleLink.resource_type).where(
                    WebsiteGoogleLink.website_id == website.id
                )
            )
        ).scalars()
    )
    ga4_linked = ResourceType.GA4_PROPERTY in linked_types
    gsc_linked = ResourceType.GSC_SITE in linked_types
    connection_statuses = set(
        (
            await session.execute(
                select(GoogleConnection.status).where(
                    GoogleConnection.workspace_id == website.workspace_id
                )
            )
        ).scalars()
    )
    if ConnectionStatus.ACTIVE in connection_statuses:
        google_connection = "active"
    elif ConnectionStatus.NEEDS_REAUTH in connection_statuses:
        google_connection = "needs_reauth"
    else:
        google_connection = "none"

    # Tri stable : à couche et poids égaux, l'ordre du catalogue départage (déterministe).
    ordered = sorted(ITEMS, key=lambda i: (LAYER_ORDER.index(i.layer), -i.weight))
    items: list[dict[str, Any]] = []
    layer_totals: dict[str, dict[str, int]] = {
        layer: {"total": 0, "done": 0} for layer in LAYER_ORDER
    }
    last_checked: datetime | None = None
    for item in ordered:
        row = rows.get(item.id)
        state = row.state if row else "unknown"
        done = _is_done(item, state)
        partial = state == "on_page" and item.max_level == "received"
        if state not in ("not_applicable", "dismissed"):
            layer_totals[item.layer]["total"] += 1
            layer_totals[item.layer]["done"] += 1 if done else 0
        if row is not None and (last_checked is None or row.checked_at > last_checked):
            last_checked = row.checked_at
        items.append(
            {
                "id": item.id,
                "layer": item.layer,
                "title": item.title,
                "why": item.why,
                "weight": item.weight,
                "quick_win": item.quick_win,
                "max_level": item.max_level,
                "state": state,
                "done": done,
                "partial": partial,
                "reason": row.reason if row else None,
                "evidence": dict(row.evidence) if row else {},
                "checked_at": row.checked_at if row else None,
                "guide": list(item.guide),
                "actions": list(item.actions),
                "snippet": _snippet_dict(item, website),
            }
        )

    overall_total = sum(t["total"] for t in layer_totals.values())
    overall_done = sum(t["done"] for t in layer_totals.values())
    return {
        "website_id": website.id,
        "profile": {
            "detected_types": detected,
            "confirmed_types": confirmed,
            "effective_types": effective,
            "needs_confirmation": confirmed is None,
            "params": {
                "ads_conversion_id": params.get("ads_conversion_id"),
                "ads_conversion_label": params.get("ads_conversion_label"),
                "uses_google_ads": params.get("uses_google_ads"),
                "ga4_measurement_id": params.get("ga4_measurement_id"),
            },
        },
        "ga4_connected": ga4_linked,
        "gsc_linked": gsc_linked,
        "google_connection": google_connection,
        "next_actions": _next_action_ids(items) if last_checked is not None else [],
        "last_checked_at": last_checked,
        "headless_checked_at": profile.headless_checked_at if profile else None,
        "overall_done": overall_done,
        "overall_total": overall_total,
        "overall_percent": round(100 * overall_done / overall_total) if overall_total else 0,
        "layers": [
            {"layer": layer, "total": layer_totals[layer]["total"], "done": layer_totals[layer]["done"]}
            for layer in LAYER_ORDER
        ],
        "items": items,
    }
