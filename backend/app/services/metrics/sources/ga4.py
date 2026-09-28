"""Source GA4 Data API (`runReport`) : totaux journaliers et événements (top N par jour).

Les métriques sont lues par NOM d'en-tête (`metricHeaders`), jamais par position
supposée. Un jour absent de la réponse reste absent (GA4 omet les jours sans donnée :
on n'invente pas de zéro). Toute forme inattendue lève `SourceError("api_error")`."""

from __future__ import annotations

import math
from collections import defaultdict
from datetime import date, datetime
from typing import Any

import httpx

from app.models.website import Website
from app.services.ga4 import _RUN_REPORT_URL, _property_number
from app.services.metrics.dimensions import clean_event
from app.services.metrics.registry import metric_def
from app.services.metrics.sources.google_http import RECOVERABLE_REASONS, google_json
from app.services.metrics.types import SOURCE_SPECS, DayRange, Observation, SourceError, SourceSpec

# Nom court (registre) -> nom de la métrique GA4.
TOTALS: dict[str, str] = {
    "sessions": "sessions",
    "screen_page_views": "screenPageViews",
    "engaged_sessions": "engagedSessions",
    "key_events": "keyEvents",
    "total_revenue": "totalRevenue",
}
_TOTALS_LIMIT = 1000
_EVENTS_LIMIT = 25000
# Plafond de pages par requête : au-delà, la collecte échoue (`truncated`) plutôt que de
# renvoyer des données partielles.
_MAX_PAGES = 20
EVENT_TOP_N = metric_def("ga4", "event_count").top_n  # type: ignore[union-attr]


def _api_error() -> SourceError:
    return SourceError("api_error", recoverable=True)


def _rows(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        raise _api_error()
    rows = payload.get("rows", [])
    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        raise _api_error()
    return rows


def _metric_index(payload: dict[str, Any]) -> dict[str, int]:
    headers = payload.get("metricHeaders")
    if not isinstance(headers, list):
        raise _api_error()
    index: dict[str, int] = {}
    for position, header in enumerate(headers):
        if not isinstance(header, dict) or not isinstance(header.get("name"), str):
            raise _api_error()
        index[header["name"]] = position
    return index


def _cells(row: dict[str, Any], key: str, count: int) -> list[str]:
    cells = row.get(key)
    if not isinstance(cells, list) or len(cells) < count:
        raise _api_error()
    values: list[str] = []
    for cell in cells:
        if not isinstance(cell, dict) or not isinstance(cell.get("value"), str):
            raise _api_error()
        values.append(cell["value"])
    return values


def _day(raw: str) -> date:
    try:
        return datetime.strptime(raw, "%Y%m%d").date()
    except ValueError:
        raise _api_error() from None


def _number(raw: str) -> float:
    try:
        value = float(raw)
    except ValueError:
        raise _api_error() from None
    if not math.isfinite(value):
        raise _api_error()
    return value


def parse_totals(payload: Any) -> list[Observation]:
    rows = _rows(payload)
    index = _metric_index(payload)  # une réponse sans en-têtes n'est pas « aucune donnée »
    if not rows:
        return []
    if any(api_name not in index for api_name in TOTALS.values()):
        raise _api_error()
    # Une ligne identique répétée pour un même jour n'est pas comptée deux fois ; deux
    # lignes de valeurs différentes pour la même clé sont une réponse incohérente.
    by_day: dict[date, list[Observation]] = {}
    for row in rows:
        day = _day(_cells(row, "dimensionValues", 1)[0])
        metrics = _cells(row, "metricValues", len(index))
        values = [
            Observation(name, day, _number(metrics[index[api_name]]))
            for name, api_name in TOTALS.items()
        ]
        if by_day.setdefault(day, values) != values:
            raise _api_error()
    return [obs for day in sorted(by_day) for obs in by_day[day]]


def parse_events(payload: Any, *, top_n: int) -> list[Observation]:
    rows = _rows(payload)
    index = _metric_index(payload)
    if not rows:
        return []
    if "eventCount" not in index:
        raise _api_error()
    # Dédoublonnage sur les dimensions BRUTES (jour, nom reçu) : une ligne identique
    # répétée par Google n'est pas additionnée (des valeurs différentes pour la même clé
    # sont une réponse incohérente). Seules les collisions dues au nettoyage sont sommées.
    raw_counts: dict[tuple[date, str], float] = {}
    for row in rows:
        raw_day, raw_name = _cells(row, "dimensionValues", 2)[:2]
        day = _day(raw_day)
        count = _number(_cells(row, "metricValues", len(index))[index["eventCount"]])
        if raw_counts.setdefault((day, raw_name), count) != count:
            raise _api_error()
    per_day: dict[date, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for (day, raw_name), count in raw_counts.items():
        name = clean_event(raw_name)
        if name is not None:
            per_day[day][name] += count
    observations: list[Observation] = []
    for day in sorted(per_day):
        ranked = sorted(per_day[day].items(), key=lambda item: (-item[1], item[0]))[:top_n]
        observations.extend(
            Observation("event_count", day, count, {"event_name": name}) for name, count in ranked
        )
    return observations


async def _report(
    url: str, token: str, body: dict[str, Any], *, limit: int, client: httpx.AsyncClient | None
) -> dict[str, Any]:
    """Lit toutes les pages d'un rapport (`offset`/`limit`) et renvoie une réponse unique.

    S'arrête quand `rowCount` est atteint, ou (à défaut) quand une page est incomplète.
    Le plafond de pages atteint lève `truncated` : jamais une collecte silencieusement
    partielle."""
    first: dict[str, Any] | None = None
    rows: list[dict[str, Any]] = []
    for _ in range(_MAX_PAGES):
        payload = await google_json(
            "POST", url, token, json={**body, "limit": limit, "offset": len(rows)}, client=client
        )
        page = _rows(payload)
        first = first if first is not None else payload
        rows.extend(page)
        total = payload.get("rowCount")
        if isinstance(total, int) and not isinstance(total, bool):
            if len(rows) >= total:
                break
            if not page:  # Google annonce plus de lignes qu'il n'en sert : incohérent
                raise SourceError("truncated", recoverable=True)
        elif len(page) < limit:
            break
    else:
        raise SourceError("truncated", recoverable=True)
    if first is None:  # inatteignable : _MAX_PAGES >= 1
        raise _api_error()
    return {**first, "rows": rows}


class Ga4Source:
    spec: SourceSpec = SOURCE_SPECS["ga4"]

    def __init__(
        self,
        *,
        property_id: str | None,
        token: str | None,
        token_problem: str | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._property_id = property_id
        self._token = token
        # Raison de l'absence de jeton (`resolve_google_credentials`) : récupérable ou non.
        self._token_problem = token_problem or "token_unavailable"
        self._client = client

    async def collect(self, website: Website, day_range: DayRange) -> list[Observation]:
        _ = website
        if not self._property_id:
            raise SourceError("ga4_not_connected", recoverable=False, not_applicable=True)
        if not self._token:
            raise SourceError(
                self._token_problem,
                recoverable=RECOVERABLE_REASONS.get(self._token_problem, False),
            )
        url = _RUN_REPORT_URL.format(pid=_property_number(self._property_id))
        observations: list[Observation] = []
        for chunk in day_range.chunks(self.spec.max_days_per_call):
            date_ranges = [{"startDate": chunk.start.isoformat(), "endDate": chunk.end.isoformat()}]
            totals = await _report(
                url,
                self._token,
                {
                    "dateRanges": date_ranges,
                    "dimensions": [{"name": "date"}],
                    "metrics": [{"name": api_name} for api_name in TOTALS.values()],
                },
                limit=_TOTALS_LIMIT,
                client=self._client,
            )
            observations.extend(o for o in parse_totals(totals) if chunk.contains(o.day))
            events = await _report(
                url,
                self._token,
                {
                    "dateRanges": date_ranges,
                    "dimensions": [{"name": "date"}, {"name": "eventName"}],
                    "metrics": [{"name": "eventCount"}],
                },
                limit=_EVENTS_LIMIT,
                client=self._client,
            )
            observations.extend(
                o for o in parse_events(events, top_n=EVENT_TOP_N) if chunk.contains(o.day)
            )
        return observations
