"""Source Core Web Vitals des visiteurs réels (CrUX, via PageSpeed Insights).

Valeur terrain = 75e centile de l'ORIGINE (`originLoadingExperience`, fenêtre glissante
de 28 jours calculée par Google), datée du jour de collecte. Sans donnée terrain,
aucune observation terrain : jamais le laboratoire à la place, jamais zéro. Le score
Lighthouse (laboratoire) est stocké à part (`performance_score`).

Validation de forme : une clé ABSENTE est « pas de donnée » (légitime : origine trop
petite), une valeur PRÉSENTE mais invalide (mauvais type, négative, booléenne, NaN, hors
bornes) est une réponse inattendue (`api_error`, récupérable), jamais stockée ni ignorée
en silence."""

from __future__ import annotations

import math
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
from app.services.pagespeed import PAGESPEED_URL

_TIMEOUT = httpx.Timeout(60.0)
_FIELD_METRICS: dict[str, tuple[str, ...]] = {
    "lcp_p75_ms": ("LARGEST_CONTENTFUL_PAINT_MS",),
    "inp_p75_ms": ("INTERACTION_TO_NEXT_PAINT", "EXPERIMENTAL_INTERACTION_TO_NEXT_PAINT"),
    "cls_p75": ("CUMULATIVE_LAYOUT_SHIFT_SCORE",),
}


def _bad_shape() -> SourceError:
    return SourceError("api_error", recoverable=True)


def _section(value: dict[str, Any], key: str) -> dict[str, Any]:
    """Sous-objet d'une réponse : `{}` si la clé est absente, erreur si elle est présente
    mais n'est pas un objet."""
    if key not in value:
        return {}
    inner = value[key]
    if not isinstance(inner, dict):
        raise _bad_shape()
    return inner


def _finite_number(value: Any) -> float | None:
    """`value` en flottant si c'est un nombre JSON fini (jamais un booléen), sinon `None`.

    Un entier JSON géant (`10**400`) est valide en JSON mais ne tient pas dans un flottant :
    `OverflowError`, traité comme une valeur invalide."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    try:
        number = float(value)
    except OverflowError:
        return None
    return number if math.isfinite(number) else None


def _percentile(metrics: dict[str, Any], *keys: str) -> float | None:
    """Premier percentile présent parmi `keys` ; `None` si aucune clé n'est présente."""
    for key in keys:
        if key not in metrics:
            continue
        entry = metrics[key]
        if not isinstance(entry, dict):
            raise _bad_shape()
        number = _finite_number(entry.get("percentile"))
        if number is None or number < 0:
            raise _bad_shape()
        return number
    return None


def parse_cwv(payload: Any, *, day: date) -> list[Observation]:
    if not isinstance(payload, dict):
        raise _bad_shape()
    # Le bloc laboratoire est toujours renvoyé : son absence, c'est une réponse tronquée
    # ou étrangère, pas « un site sans données ».
    lighthouse = payload.get("lighthouseResult")
    if not isinstance(lighthouse, dict):
        raise _bad_shape()
    runtime_error = lighthouse.get("runtimeError")
    if runtime_error is not None:
        if not isinstance(runtime_error, dict):
            raise _bad_shape()
        code = runtime_error.get("code")
        if isinstance(code, str) and code and code != "NO_ERROR":
            # Lighthouse dit explicitement ne pas avoir pu mesurer la page (ex. NO_FCP,
            # PROTOCOL_TIMEOUT) : un `score: null` qui suit n'est pas « pas de donnée »,
            # c'est un site injoignable ce jour-là.
            raise SourceError("site_unreachable", recoverable=False)
    metrics = _section(_section(payload, "originLoadingExperience"), "metrics")
    observations: list[Observation] = []
    for name, keys in _FIELD_METRICS.items():
        percentile = _percentile(metrics, *keys)
        if percentile is None:
            continue
        # CrUX donne le CLS multiplié par 100.
        value = percentile / 100 if name == "cls_p75" else percentile
        observations.append(Observation(name, day, value))
    performance = _section(_section(lighthouse, "categories"), "performance")
    # `score: null` est la réponse de Lighthouse quand la mesure a échoué : pas de donnée.
    score = performance.get("score")
    if score is not None:
        number = _finite_number(score)
        if number is None or not 0 <= number <= 1:
            raise _bad_shape()
        observations.append(Observation("performance_score", day, round(number * 100, 1)))
    return observations


# Raisons Google (`error.details[].reason`, `error.errors[].reason`, `error.status`) qui
# désignent NOTRE configuration serveur (clé invalide, API désactivée, clé restreinte) :
# jamais une panne du site du client.
_KEY_REJECTED_REASONS = frozenset(
    {
        "API_KEY_INVALID",
        "keyInvalid",
        "SERVICE_DISABLED",
        "accessNotConfigured",
        "API_KEY_SERVICE_BLOCKED",
        "API_KEY_HTTP_REFERRER_BLOCKED",
        "API_KEY_IP_ADDRESS_BLOCKED",
        "API_KEY_ANDROID_APP_BLOCKED",
        "API_KEY_IOS_APP_BLOCKED",
        "PERMISSION_DENIED",
        "UNAUTHENTICATED",
    }
)
_QUOTA_REASONS = frozenset(
    {"RESOURCE_EXHAUSTED", "rateLimitExceeded", "dailyLimitExceeded", "quotaExceeded"}
)
# Erreurs Lighthouse qui disent que la page du site n'a pas pu être chargée.
_SITE_UNREACHABLE_MARKERS = ("FAILED_DOCUMENT_REQUEST", "ERRORED_DOCUMENT_REQUEST", "DNS_FAILURE")


def _error_facts(response: httpx.Response) -> tuple[set[str], bool]:
    """(codes de raison, page injoignable ?) lus dans le corps d'erreur Google.

    Rien du corps n'est recopié : seuls des codes connus sont comparés, le message
    (qui peut citer l'URL ou la clé) n'est jamais conservé ni renvoyé."""
    try:
        body = response.json()
    except ValueError:
        return set(), False
    error = body.get("error") if isinstance(body, dict) else None
    if not isinstance(error, dict):
        return set(), False
    reasons: set[str] = set()
    status = error.get("status")
    if isinstance(status, str):
        reasons.add(status)
    for list_key in ("details", "errors"):
        items = error.get(list_key)
        for item in items if isinstance(items, list) else []:
            reason = item.get("reason") if isinstance(item, dict) else None
            if isinstance(reason, str):
                reasons.add(reason)
    message = error.get("message")
    unreachable = isinstance(message, str) and any(
        marker in message for marker in _SITE_UNREACHABLE_MARKERS
    )
    return reasons, unreachable or "FAILED_DOCUMENT_REQUEST" in reasons


def _raise_for_pagespeed(response: httpx.Response) -> None:
    status = response.status_code
    if status < 400:
        return
    reasons, page_unreachable = _error_facts(response)
    if status == 429 or reasons & _QUOTA_REASONS:
        raise SourceError("quota", recoverable=True)
    if status in (401, 403) or reasons & _KEY_REJECTED_REASONS:
        # Notre clé est refusée, l'API est désactivée ou la clé restreinte : problème de
        # configuration serveur, pas une action à demander au client.
        raise SourceError("api_key_rejected", recoverable=False)
    if page_unreachable:
        raise SourceError("site_unreachable", recoverable=False)
    if status == 400:
        raise SourceError("bad_request", recoverable=False)
    if status in (408, 425) or status >= 500:
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
        if self._api_key and not (self._api_key.isascii() and self._api_key.isprintable()):
            # Une clé non ASCII ne peut pas être encodée en en-tête : clé mal saisie,
            # donc rejetée par principe (jamais recopiée dans l'erreur).
            raise SourceError("api_key_rejected", recoverable=False)
        # La clé voyage dans un en-tête : une URL peut finir dans un log ou une exception.
        headers = {"X-Goog-Api-Key": self._api_key} if self._api_key else {}
        owns = self._client is None
        http = self._client or httpx.AsyncClient(timeout=_TIMEOUT)
        try:
            try:
                response = await http.get(PAGESPEED_URL, params=params, headers=headers)
            except httpx.InvalidURL:
                raise SourceError("bad_request", recoverable=False) from None
            except httpx.HTTPError:
                # L'exception httpx porte la requête : jamais chaînée.
                raise SourceError("network", recoverable=True) from None
        finally:
            if owns:
                await http.aclose()
        _raise_for_pagespeed(response)
        try:
            payload = response.json()
        except ValueError:
            raise _bad_shape() from None
        return parse_cwv(payload, day=day)
