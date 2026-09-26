"""Source Core Web Vitals des visiteurs réels (CrUX, via PageSpeed Insights).

Valeur terrain = 75e centile de l'ORIGINE (`originLoadingExperience`, fenêtre glissante
de 28 jours calculée par Google), datée du jour de collecte. Sans donnée terrain,
aucune observation terrain : jamais le laboratoire à la place, jamais zéro. Le score
Lighthouse (laboratoire) est stocké à part (`performance_score`)."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from typing import Any

import httpx

from app.models.website import Website
from app.services.metrics.types import (
    SOURCE_SPECS,
    DayRange,
    Observation,
    SourceError,
    SourceSpec,
    utc_today,
)
from app.services.pagespeed import PAGESPEED_URL, _field_percentile

_TIMEOUT = httpx.Timeout(60.0)
_FIELD_METRICS: dict[str, tuple[str, ...]] = {
    "lcp_p75_ms": ("LARGEST_CONTENTFUL_PAINT_MS",),
    "inp_p75_ms": ("INTERACTION_TO_NEXT_PAINT", "EXPERIMENTAL_INTERACTION_TO_NEXT_PAINT"),
    "cls_p75": ("CUMULATIVE_LAYOUT_SHIFT_SCORE",),
}


def _section(value: Any, key: str) -> dict[str, Any]:
    inner = value.get(key) if isinstance(value, dict) else None
    return inner if isinstance(inner, dict) else {}


def parse_cwv(payload: Any, *, day: date) -> list[Observation]:
    if not isinstance(payload, dict):
        raise SourceError("api_error", recoverable=True)
    metrics = _section(_section(payload, "originLoadingExperience"), "metrics")
    observations: list[Observation] = []
    for name, keys in _FIELD_METRICS.items():
        try:
            percentile = _field_percentile(metrics, *keys)
        except (ValueError, OverflowError):
            # Percentile NaN ou infini : réponse de forme inattendue, jamais une mesure.
            raise SourceError("api_error", recoverable=True) from None
        if percentile is None:
            continue
        # CrUX donne le CLS multiplié par 100.
        value = percentile / 100 if name == "cls_p75" else float(percentile)
        observations.append(Observation(name, day, value))
    performance = _section(
        _section(_section(payload, "lighthouseResult"), "categories"), "performance"
    )
    score = performance.get("score")
    if isinstance(score, int | float) and not isinstance(score, bool) and 0 <= score <= 1:
        observations.append(Observation("performance_score", day, round(score * 100, 1)))
    return observations


def _raise_for_pagespeed(status: int) -> None:
    if status < 400:
        return
    if status == 429:
        raise SourceError("quota", recoverable=True)
    if status == 400:
        # PageSpeed n'a pas pu charger la page (DNS, TLS, 4xx du site...).
        raise SourceError("site_unreachable", recoverable=False)
    if status in (401, 403):
        raise SourceError("permission_or_api_disabled", recoverable=False)
    if status >= 500:
        raise SourceError("api_error", recoverable=True)
    raise SourceError("api_error", recoverable=False)


class CwvSource:
    spec: SourceSpec = SOURCE_SPECS["cwv"]

    def __init__(
        self,
        *,
        api_key: str | None,
        client: httpx.AsyncClient | None = None,
        today: Callable[[], date] = utc_today,
    ) -> None:
        self._api_key = api_key
        self._client = client
        self._today = today

    async def collect(self, website: Website, day_range: DayRange) -> list[Observation]:
        day = self._today()
        if not day_range.contains(day):
            return []
        params = {
            "url": f"https://{website.domain}",
            "strategy": "mobile",
            "category": "performance",
        }
        if self._api_key:
            params["key"] = self._api_key
        owns = self._client is None
        http = self._client or httpx.AsyncClient(timeout=_TIMEOUT)
        try:
            try:
                response = await http.get(PAGESPEED_URL, params=params)
            except httpx.HTTPError:
                # L'exception httpx porte l'URL, donc la clé : jamais chaînée.
                raise SourceError("network", recoverable=True) from None
        finally:
            if owns:
                await http.aclose()
        _raise_for_pagespeed(response.status_code)
        try:
            payload = response.json()
        except ValueError:
            raise SourceError("api_error", recoverable=True) from None
        return parse_cwv(payload, day=day)
