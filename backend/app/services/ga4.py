"""Client + parseur Google Analytics 4 Data API (`runReport`).

`fetch_event_metrics` fait l'appel HTTP (mockable via `httpx.MockTransport`)
et `parse_run_report` est pur, teste sur des fixtures JSON reelles. Token
revoque (401) / quota depasse (403) / reseau -> `Ga4Signals` degrade
(`degraded=True`, score 0) : l'audit global ne crashe jamais.

Regles derivees :
- `page_view` absent / a 0 -> flux GA4 casse (score tres bas).
- `purchase` recu mais `totalRevenue` ET `eventValue` a 0 -> parametres
  marchands manquants (`purchase_missing_params`).
- `generate_lead` a 0 alors que le site a du trafic -> evenement jamais recu.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.services.audit_signals import Ga4Signals

logger = logging.getLogger(__name__)

_RUN_REPORT_URL = "https://analyticsdata.googleapis.com/v1beta/properties/{pid}:runReport"
_TIMEOUT = httpx.Timeout(20.0)


def _property_number(property_id: str) -> str:
    """`properties/447213908` ou `447213908` -> `447213908`."""
    return property_id.rsplit("/", 1)[-1].strip()


def _metric(values: list, index: int) -> float:
    try:
        return float(values[index].get("value", 0))
    except (IndexError, TypeError, ValueError, AttributeError):
        return 0.0


def parse_run_report(payload: dict[str, Any]) -> Ga4Signals:
    rows = payload.get("rows", []) if isinstance(payload, dict) else []
    events: dict[str, dict[str, float]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        dims = row.get("dimensionValues") or []
        metrics = row.get("metricValues") or []
        if not dims or not isinstance(dims[0], dict):
            continue
        name = dims[0].get("value")
        if not isinstance(name, str) or not name:
            continue
        events[name] = {
            "count": _metric(metrics, 0),
            "revenue": _metric(metrics, 1),
            "value": _metric(metrics, 2),
        }

    page_views = events.get("page_view", {}).get("count", 0.0)
    purchase = events.get("purchase")
    generate_lead = events.get("generate_lead", {}).get("count", 0.0)

    purchase_missing_params: tuple[str, ...] = ()
    if purchase and purchase["count"] > 0 and purchase["revenue"] == 0 and purchase["value"] == 0:
        purchase_missing_params = ("value", "currency")

    missing_events: list[str] = []
    if page_views > 0 and generate_lead == 0:
        missing_events.append("generate_lead")

    if page_views == 0:
        score = 15  # GA4 ne recoit plus rien
    elif purchase_missing_params or missing_events:
        score = 60
    else:
        score = 90

    return Ga4Signals(
        score=score,
        purchase_missing_params=purchase_missing_params,
        missing_events=tuple(missing_events),
    )


async def fetch_event_metrics(
    access_token: str,
    property_id: str,
    *,
    days: int = 30,
    client: httpx.AsyncClient | None = None,
) -> Ga4Signals:
    body = {
        "dateRanges": [{"startDate": f"{days}daysAgo", "endDate": "today"}],
        "dimensions": [{"name": "eventName"}],
        "metrics": [
            {"name": "eventCount"},
            {"name": "totalRevenue"},
            {"name": "eventValue"},
        ],
    }
    url = _RUN_REPORT_URL.format(pid=_property_number(property_id))

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
            "GA4 Data API %s pour %s : %s",
            exc.response.status_code,
            property_id,
            exc.response.text[:200],
        )
        return Ga4Signals(score=0, degraded=True)
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("GA4 Data API indisponible pour %s : %s", property_id, exc)
        return Ga4Signals(score=0, degraded=True)
    finally:
        if owns_client:
            await http.aclose()

    return parse_run_report(payload)
