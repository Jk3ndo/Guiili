"""Client + parseur PageSpeed Insights v5 (stratégie mobile).

`fetch_pagespeed` fait l'appel HTTP (mockable via `httpx.MockTransport`) ;
`parse_pagespeed` est pur et testé sur des fixtures JSON réelles. Les deux
retournent un dict de kwargs pour `CwvSignals`. Échec réseau / quota -> dict
dégradé ``{"score": 0}``.
"""

from __future__ import annotations

from typing import Any

import httpx

PAGESPEED_URL = "https://www.googleapis.com/pagespeedonline/v5/runPagespeed"
_TIMEOUT = httpx.Timeout(30.0)


def _short_url(url: str) -> str:
    """`https://cdn.x/assets/hero-large.jpg?v=3` -> `hero-large.jpg`."""
    try:
        parsed = httpx.URL(url)
    except (TypeError, httpx.InvalidURL):
        return url[:60]
    tail = parsed.path.rstrip("/").rsplit("/", 1)[-1]
    return tail or parsed.host or url[:60]


def _audit(audits: dict, key: str) -> dict:
    value = audits.get(key)
    return value if isinstance(value, dict) else {}


def _audit_numeric(audits: dict, key: str) -> float | None:
    value = _audit(audits, key).get("numericValue")
    return float(value) if isinstance(value, int | float) else None


def _audit_ms(audits: dict, key: str) -> int | None:
    value = _audit_numeric(audits, key)
    return round(value) if value is not None else None


def _audit_item_urls(audits: dict, key: str) -> list[str]:
    items = _audit(audits, key).get("details", {}).get("items", [])
    return [_short_url(item["url"]) for item in items if isinstance(item, dict) and item.get("url")]


def _third_party_entities(audits: dict) -> list[str]:
    items = _audit(audits, "third-party-summary").get("details", {}).get("items", [])
    names: list[str] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        entity = item.get("entity")
        name = entity.get("text") if isinstance(entity, dict) else entity
        if isinstance(name, str) and name:
            names.append(name)
    return names


def _lcp_element(audits: dict) -> str | None:
    items = _audit(audits, "largest-contentful-paint-element").get("details", {}).get("items", [])
    for item in items:
        if not isinstance(item, dict):
            continue
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

    heavy = (
        _audit_item_urls(audits, "modern-image-formats")
        + _audit_item_urls(audits, "uses-optimized-images")
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
        "third_party_scripts": tuple(dict.fromkeys(_third_party_entities(audits)))[:5],
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
