"""Client + parseur Google Search Console (Search Analytics API v3).

`fetch_search_analytics` fait l'appel HTTP (mockable via `httpx.MockTransport`)
et `parse_search_analytics` est pur, teste sur des fixtures JSON reelles.
Token revoque (401) / quota depasse (403) / reseau -> `GscSignals` degrade
(`degraded=True`, `connection_stale_days=30` pour declencher la regle
`gsc_stale`) : l'audit global ne crashe jamais.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any
from urllib.parse import quote

import httpx

from app.services.audit_signals import GscSignals, GscUrlSample

logger = logging.getLogger(__name__)

_QUERY_URL = "https://www.googleapis.com/webmasters/v3/sites/{site}/searchAnalytics/query"
_TIMEOUT = httpx.Timeout(20.0)
_STALE_DAYS_ON_FAILURE = 30
_TOP_URLS = 10


def _degraded() -> GscSignals:
    return GscSignals(score=0, connection_stale_days=_STALE_DAYS_ON_FAILURE, degraded=True)


def _relative_path(url: str) -> str:
    """`https://boutique-verte.fr/collections/homme?x=1` -> `/collections/homme`."""
    try:
        parsed = httpx.URL(url)
    except (TypeError, httpx.InvalidURL):
        return url[:80]
    return parsed.path or "/"


def _as_int(value: object) -> int:
    return round(value) if isinstance(value, int | float) else 0


def parse_search_analytics(payload: dict[str, Any]) -> GscSignals:
    rows = payload.get("rows", []) if isinstance(payload, dict) else []
    parsed: list[tuple[str, int, int]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        keys = row.get("keys") or []
        if not keys or not isinstance(keys[0], str):
            continue
        parsed.append((keys[0], _as_int(row.get("clicks")), _as_int(row.get("impressions"))))

    parsed.sort(key=lambda item: item[1], reverse=True)
    if not parsed:
        return GscSignals(score=0)

    samples = tuple(
        GscUrlSample(_relative_path(url), "Indexée", clicks, impressions)
        for url, clicks, impressions in parsed[:_TOP_URLS]
    )
    total_clicks = sum(clicks for _, clicks, _ in parsed)
    total_impressions = sum(impressions for _, _, impressions in parsed)
    avg_ctr = (total_clicks / total_impressions * 100) if total_impressions else 0.0
    # Score sante : presence de donnees + CTR moyen (borne 20..100).
    score = max(20, min(100, round(45 + avg_ctr * 12)))

    return GscSignals(
        score=score,
        valid_pages=len(parsed),
        excluded_pages=0,
        sample_urls=samples,
    )


async def fetch_search_analytics(
    access_token: str,
    site_url: str,
    *,
    days: int = 30,
    client: httpx.AsyncClient | None = None,
) -> GscSignals:
    end = date.today()
    start = end - timedelta(days=days)
    body = {
        "startDate": start.isoformat(),
        "endDate": end.isoformat(),
        "dimensions": ["page"],
        "rowLimit": 25,
    }
    url = _QUERY_URL.format(site=quote(site_url, safe=""))

    owns_client = client is None
    http = client or httpx.AsyncClient(timeout=_TIMEOUT)
    try:
        response = await http.post(
            url, json=body, headers={"Authorization": f"Bearer {access_token}"}
        )
        response.raise_for_status()
        payload = response.json()
    except httpx.HTTPStatusError as exc:
        logger.warning(
            "Search Console %s pour %s : %s",
            exc.response.status_code,
            site_url,
            exc.response.text[:200],
        )
        return _degraded()
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("Search Console indisponible pour %s : %s", site_url, exc)
        return _degraded()
    finally:
        if owns_client:
            await http.aclose()

    return parse_search_analytics(payload)
