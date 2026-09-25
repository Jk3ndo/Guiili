"""Suivi d'erreurs Sentry, désactivé tant que SENTRY_DSN est vide.

Règle : Sentry ne reçoit jamais de contenu de requête. On coupe l'envoi du corps, des
cookies, des en-têtes et de la chaîne de requête à la source ET on nettoie chaque
événement (`scrub_event`) pour les données ajoutées ailleurs (extra, contextes) et pour
les URL sortantes (`?key=...`) que les messages d'exception peuvent embarquer.
"""

from __future__ import annotations

import os
import re
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import sentry_sdk

from app.config import Settings

_FILTERED = "[Filtered]"
# Noms courts : correspondance exacte (évite de masquer « status_code »).
_EXACT_KEYS = frozenset({"code", "state", "key"})
# Fragments : correspondance par sous-chaîne.
_SUBSTRING_KEYS = (
    "password",
    "secret",
    "token",
    "authorization",
    "cookie",
    "api_key",
    "apikey",
    "refresh",
)
_DROPPED_REQUEST_KEYS = ("query_string", "cookies", "headers", "data")
# Une URL http(s) suivie de sa chaîne de requête, jusqu'au premier espace ou guillemet.
_URL_QUERY = re.compile(r"(https?://[^\s?'\"<>)\]]*)\?[^\s'\"<>)\]]*")


# Chaîne de requête et fragment d'URL tels que les posent les intégrations httpx/stdlib
# (`http.query`, `http.fragment`, `url.query`...) : brute, donc jamais reconnue comme URL.
_QUERY_KEY_SUFFIXES = ("query", "query_string", "fragment")


def _is_sensitive(key: str) -> bool:
    lowered = key.lower().replace("-", "_")  # « x-api-key » -> « x_api_key »
    return (
        lowered in _EXACT_KEYS
        or lowered.endswith(_QUERY_KEY_SUFFIXES)
        or any(part in lowered for part in _SUBSTRING_KEYS)
    )


def _mask_url_queries(text: str) -> str:
    return _URL_QUERY.sub(rf"\1?{_FILTERED}", text)


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _FILTERED if isinstance(key, str) and _is_sensitive(key) else _redact(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_redact(item) for item in value]
    if isinstance(value, str):
        return _mask_url_queries(value)
    return value


def _scrub_texts(event: dict[str, Any]) -> None:
    """Masque les chaînes de requête d'URL dans les messages et valeurs d'exception."""
    if isinstance(event.get("message"), str):
        event["message"] = _mask_url_queries(event["message"])
    logentry = event.get("logentry")
    if isinstance(logentry, dict):
        for key in ("message", "formatted"):
            if isinstance(logentry.get(key), str):
                logentry[key] = _mask_url_queries(logentry[key])
        if "params" in logentry:  # arguments de `logger.error("... %s", url)`
            logentry["params"] = _redact(logentry["params"])
    exception = event.get("exception")
    values = exception.get("values") if isinstance(exception, dict) else None
    if isinstance(values, list):
        for item in values:
            if isinstance(item, dict) and isinstance(item.get("value"), str):
                item["value"] = _mask_url_queries(item["value"])


def _scrub_spans(event: dict[str, Any]) -> None:
    """Nettoie les spans d'une transaction (`http.query`, `data.url`, description)."""
    spans = event.get("spans")
    if not isinstance(spans, list):
        return
    for span in spans:
        if not isinstance(span, dict):
            continue
        if "data" in span:
            span["data"] = _redact(span["data"])
        if isinstance(span.get("description"), str):
            span["description"] = _mask_url_queries(span["description"])


def scrub_event(event: dict[str, Any], hint: dict[str, Any]) -> dict[str, Any] | None:
    """Purge un événement d'erreur avant envoi (`before_send`)."""
    request = event.get("request")
    if isinstance(request, dict):
        for key in _DROPPED_REQUEST_KEYS:
            request.pop(key, None)
        url = request.get("url")
        if isinstance(url, str):
            parts = urlsplit(url)
            request["url"] = urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))
    for section in ("extra", "contexts", "tags", "breadcrumbs"):
        if section in event:
            event[section] = _redact(event[section])
    _scrub_texts(event)
    _scrub_spans(event)
    return event


def scrub_transaction(event: dict[str, Any], hint: dict[str, Any]) -> dict[str, Any] | None:
    """Même purge pour les transactions de traçage (`before_send_transaction`).

    Sentry n'appelle pas `before_send` pour les transactions : sans ceci, les spans
    httpx (`http.query`, `data.url`) partiraient bruts dès que le taux d'échantillonnage
    est non nul.
    """
    return scrub_event(event, hint)


def init_sentry(settings: Settings) -> bool:
    dsn = settings.sentry_dsn.get_secret_value()
    if not dsn:
        return False
    sentry_sdk.init(
        dsn=dsn,
        environment=settings.environment,
        release=os.environ.get("K_REVISION") or None,
        send_default_pii=False,
        traces_sample_rate=settings.sentry_traces_sample_rate,
        max_request_body_size="never",
        include_local_variables=False,
        before_send=scrub_event,
        before_send_transaction=scrub_transaction,
    )
    return True
