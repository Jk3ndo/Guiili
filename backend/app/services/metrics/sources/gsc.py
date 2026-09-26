"""Source Search Console (Search Analytics) : totaux journaliers (clics, impressions,
CTR, position) puis top N pages et requêtes par jour (clics et impressions).

Les pages sont réduites au chemin (plusieurs URL peuvent donner le même chemin : on
additionne) ; les requêtes personnelles sont écartées (voir `dimensions.py`). Seules les
données finales sont lues (`dataState: final`)."""

from __future__ import annotations

import math
from collections import defaultdict
from datetime import date
from typing import Any
from urllib.parse import quote

import httpx

from app.models.website import Website
from app.services.gsc import _QUERY_URL
from app.services.metrics.dimensions import CLEANERS
from app.services.metrics.registry import metric_def
from app.services.metrics.sources.google_http import google_json
from app.services.metrics.types import SOURCE_SPECS, DayRange, Observation, SourceError, SourceSpec

_ROW_LIMIT = 25000
DIMENSION_TOP_N = metric_def("gsc", "clicks").top_n  # type: ignore[union-attr]
_TOTAL_FIELDS = ("clicks", "impressions", "ctr", "position")


def _api_error() -> SourceError:
    return SourceError("api_error", recoverable=True)


def _rows(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        raise _api_error()
    rows = payload.get("rows", [])
    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        raise _api_error()
    return rows


def _keys(row: dict[str, Any], count: int) -> list[str]:
    keys = row.get("keys")
    if (
        not isinstance(keys, list)
        or len(keys) < count
        or not all(isinstance(key, str) for key in keys)
    ):
        raise _api_error()
    return keys


def _day(raw: str) -> date:
    try:
        return date.fromisoformat(raw)
    except ValueError:
        raise _api_error() from None


def _number(row: dict[str, Any], field: str) -> float:
    value = row.get(field)
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
        raise _api_error()
    return float(value)


def parse_totals(payload: Any) -> list[Observation]:
    # Dernière lecture d'un jour l'emporte : une ligne répétée n'est pas comptée deux fois.
    by_day: dict[date, list[Observation]] = {}
    for row in _rows(payload):
        day = _day(_keys(row, 1)[0])
        by_day[day] = [Observation(name, day, _number(row, name)) for name in _TOTAL_FIELDS]
    return [obs for day in sorted(by_day) for obs in by_day[day]]


def parse_dimension(payload: Any, dimension: str, *, top_n: int) -> list[Observation]:
    cleaner = CLEANERS[dimension]
    # Dédoublonnage sur les dimensions BRUTES (jour, valeur reçue) : une ligne répétée par
    # Google n'est pas additionnée. Seules les collisions dues au nettoyage le sont.
    raw_rows: dict[tuple[date, str], tuple[float, float]] = {}
    for row in _rows(payload):
        raw_day, raw_value = _keys(row, 2)[:2]
        raw_rows[(_day(raw_day), raw_value)] = (
            _number(row, "clicks"),
            _number(row, "impressions"),
        )
    merged: dict[date, dict[str, list[float]]] = defaultdict(dict)
    for (day, raw_value), (clicks, impressions) in raw_rows.items():
        value = cleaner(raw_value)
        if value is None:
            continue
        slot = merged[day].setdefault(value, [0.0, 0.0])
        slot[0] += clicks
        slot[1] += impressions
    observations: list[Observation] = []
    for day in sorted(merged):
        ranked = sorted(
            merged[day].items(), key=lambda item: (-item[1][0], -item[1][1], item[0])
        )[:top_n]
        for value, (clicks, impressions) in ranked:
            observations.append(Observation("clicks", day, clicks, {dimension: value}))
            observations.append(Observation("impressions", day, impressions, {dimension: value}))
    return observations


class GscSource:
    spec: SourceSpec = SOURCE_SPECS["gsc"]

    def __init__(
        self,
        *,
        site_url: str | None,
        token: str | None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._site_url = site_url
        self._token = token
        self._client = client

    async def _query(self, chunk: DayRange, dimensions: list[str]) -> Any:
        return await google_json(
            "POST",
            _QUERY_URL.format(site=quote(self._site_url or "", safe="")),
            self._token or "",
            json={
                "startDate": chunk.start.isoformat(),
                "endDate": chunk.end.isoformat(),
                "dimensions": dimensions,
                "rowLimit": _ROW_LIMIT,
                "dataState": "final",
            },
            client=self._client,
        )

    async def collect(self, website: Website, day_range: DayRange) -> list[Observation]:
        _ = website
        if not self._site_url:
            raise SourceError("gsc_not_connected", recoverable=False, not_applicable=True)
        if not self._token:
            raise SourceError("token_unavailable", recoverable=False)
        observations: list[Observation] = []
        for chunk in day_range.chunks(self.spec.max_days_per_call):
            parsed = parse_totals(await self._query(chunk, ["date"]))
            for dimension in ("page", "query"):
                payload = await self._query(chunk, ["date", dimension])
                parsed.extend(parse_dimension(payload, dimension, top_n=DIMENSION_TOP_N))
            observations.extend(o for o in parsed if chunk.contains(o.day))
        return observations
