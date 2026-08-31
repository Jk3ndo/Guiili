"""Client + parseur PageSpeed Insights v5 (stratégie mobile).

`fetch_pagespeed` fait l'appel HTTP (mockable via `httpx.MockTransport`) ;
`parse_pagespeed` est pur et testé sur des fixtures JSON réelles. Les deux
retournent un dict de kwargs pour `CwvSignals`. Échec réseau / quota -> dict
dégradé ``{"score": 0}``.
"""

from __future__ import annotations

from typing import Any

import httpx

from app.services.audit_signals import CostlyEntity, HeavyAsset, ShiftElement

__all__ = [
    "PAGESPEED_URL",
    "CostlyEntity",
    "HeavyAsset",
    "ShiftElement",
    "fetch_pagespeed",
    "parse_pagespeed",
]

PAGESPEED_URL = "https://www.googleapis.com/pagespeedonline/v5/runPagespeed"
_TIMEOUT = httpx.Timeout(30.0)

# Entité tierce connue -> catégorie lisible (fallback : « Script tiers »).
_ENTITY_CATEGORY: dict[str, str] = {
    "Google Tag Manager": "Tag manager",
    "Google Analytics": "Analytics",
    "Google/Doubleclick Ads": "Publicité",
    "Hotjar": "Enregistrement de session",
    "Intercom": "Chat support",
    "Zendesk": "Chat support",
    "Facebook": "Réseau social",
    "YouTube": "Vidéo",
    "Stripe": "Paiement",
}


def _short_url(url: str) -> str:
    """`https://cdn.x/assets/hero-large.jpg?v=3` -> `hero-large.jpg`."""
    try:
        parsed = httpx.URL(url)
    except (TypeError, httpx.InvalidURL):
        return url[:60]
    tail = parsed.path.rstrip("/").rsplit("/", 1)[-1]
    return tail or parsed.host or url[:60]


def _asset_format(name: str) -> str:
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    return {"jpg": "JPEG", "jpeg": "JPEG"}.get(ext, ext.upper()) or "—"


def _audit(audits: dict, key: str) -> dict:
    value = audits.get(key)
    return value if isinstance(value, dict) else {}


def _audit_items(audits: dict, key: str) -> list[dict]:
    items = _audit(audits, key).get("details", {}).get("items", [])
    return [item for item in items if isinstance(item, dict)]


def _audit_numeric(audits: dict, key: str) -> float | None:
    value = _audit(audits, key).get("numericValue")
    return float(value) if isinstance(value, int | float) else None


def _audit_ms(audits: dict, key: str) -> int | None:
    value = _audit_numeric(audits, key)
    return round(value) if value is not None else None


def _num(value: object) -> float:
    return float(value) if isinstance(value, int | float) else 0.0


def _audit_item_urls(audits: dict, key: str) -> list[str]:
    return [_short_url(item["url"]) for item in _audit_items(audits, key) if item.get("url")]


def _costly_entities(audits: dict) -> list[CostlyEntity]:
    entities: list[CostlyEntity] = []
    for item in _audit_items(audits, "third-party-summary"):
        entity = item.get("entity")
        name = entity.get("text") if isinstance(entity, dict) else entity
        if not isinstance(name, str) or not name:
            continue
        entities.append(
            CostlyEntity(
                name=name,
                category=_ENTITY_CATEGORY.get(name, "Script tiers"),
                main_thread_ms=round(_num(item.get("mainThreadTime"))),
                blocking_ms=round(_num(item.get("blockingTime"))),
            )
        )
    entities.sort(key=lambda e: e.main_thread_ms, reverse=True)
    return entities[:5]


def _heavy_image_assets(audits: dict) -> list[HeavyAsset]:
    assets: list[HeavyAsset] = []
    seen: set[str] = set()
    for key in ("modern-image-formats", "uses-optimized-images"):
        for item in _audit_items(audits, key):
            url = item.get("url")
            if not isinstance(url, str) or not url:
                continue
            name = _short_url(url)
            if name in seen:
                continue
            seen.add(name)
            assets.append(
                HeavyAsset(
                    name=name,
                    current_format=_asset_format(name),
                    size_kb=round(_num(item.get("totalBytes")) / 1024),
                    estimated_saving_kb=round(_num(item.get("wastedBytes")) / 1024),
                )
            )
    return assets[:5]


def _shift_elements(audits: dict) -> list[ShiftElement]:
    elements: list[ShiftElement] = []
    for item in _audit_items(audits, "layout-shift-elements"):
        node = item.get("node") if isinstance(item.get("node"), dict) else {}
        selector = node.get("selector") or node.get("snippet")
        if not isinstance(selector, str) or not selector:
            continue
        elements.append(
            ShiftElement(
                selector=selector[:120],
                impact=round(_num(item.get("score")), 3),
                note="Décalage de mise en page mesuré sur cet élément.",
            )
        )
    return elements[:5]


def _lcp_element(audits: dict) -> str | None:
    for item in _audit_items(audits, "largest-contentful-paint-element"):
        for node in item.get("items") or [item]:
            snippet = (node.get("node") or {}).get("snippet") if isinstance(node, dict) else None
            if isinstance(snippet, str) and snippet:
                return snippet[:120]
    return None


def _field_percentile(metrics: dict, *keys: str) -> int | None:
    for key in keys:
        entry = metrics.get(key)
        if isinstance(entry, dict) and isinstance(entry.get("percentile"), int | float):
            return round(entry["percentile"])
    return None


def parse_pagespeed(payload: dict[str, Any]) -> dict[str, Any]:
    lighthouse = payload.get("lighthouseResult", {})
    audits = lighthouse.get("audits", {})
    raw_score = lighthouse.get("categories", {}).get("performance", {}).get("score")
    score = round(raw_score * 100) if isinstance(raw_score, int | float) else 0

    field = payload.get("loadingExperience", {}).get("metrics", {})
    origin = payload.get("originLoadingExperience", {}).get("metrics", {})

    def field_value(*keys: str) -> int | None:
        return _field_percentile(field, *keys) or _field_percentile(origin, *keys)

    lcp = field_value("LARGEST_CONTENTFUL_PAINT_MS")
    inp = field_value("INTERACTION_TO_NEXT_PAINT", "EXPERIMENTAL_INTERACTION_TO_NEXT_PAINT")
    cls_pct = field_value("CUMULATIVE_LAYOUT_SHIFT_SCORE")
    has_field = lcp is not None or inp is not None

    if lcp is None:
        lcp = _audit_ms(audits, "largest-contentful-paint")
    if inp is None:
        inp = _audit_ms(audits, "interaction-to-next-paint") or _audit_ms(
            audits, "total-blocking-time"
        )
    cls = (
        cls_pct / 100.0
        if cls_pct is not None
        else _audit_numeric(audits, "cumulative-layout-shift")
    )

    entities = _costly_entities(audits)
    lcp_assets = _heavy_image_assets(audits)
    heavy = (
        [asset.name for asset in lcp_assets]
        + _audit_item_urls(audits, "unminified-javascript")
        + _audit_item_urls(audits, "unused-javascript")
    )
    blocking = _audit_item_urls(audits, "render-blocking-resources")

    return {
        "score": score,
        "lcp_ms": lcp or 0,
        "inp_ms": inp or 0,
        "cls": round(cls or 0.0, 3),
        "heavy_assets": tuple(dict.fromkeys(heavy))[:5],
        "blocking_scripts": tuple(dict.fromkeys(blocking))[:5],
        "third_party_scripts": tuple(entity.name for entity in entities),
        "costly_entities": tuple(entities),
        "lcp_assets": tuple(lcp_assets),
        "shift_elements": tuple(_shift_elements(audits)),
        "js_execution_ms": _audit_ms(audits, "bootup-time") or 0,
        "total_blocking_time_ms": _audit_ms(audits, "total-blocking-time") or 0,
        "lcp_element": _lcp_element(audits),
        "field_data": has_field,
    }


async def fetch_pagespeed(
    domain: str,
    *,
    api_key: str | None = None,
    client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    params: dict[str, str] = {
        "url": f"https://{domain}",
        "strategy": "mobile",
        "category": "performance",
    }
    if api_key:
        params["key"] = api_key

    owns_client = client is None
    http = client or httpx.AsyncClient(timeout=_TIMEOUT)
    try:
        response = await http.get(PAGESPEED_URL, params=params)
        response.raise_for_status()
        payload = response.json()
    except (httpx.HTTPError, ValueError):
        return {"score": 0, "field_data": False}  # mode dégradé explicite
    finally:
        if owns_client:
            await http.aclose()

    return parse_pagespeed(payload)
