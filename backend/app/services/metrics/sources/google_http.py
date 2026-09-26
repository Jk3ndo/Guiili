"""Appel JSON authentifié vers une API Google, erreurs converties en `SourceError`.

Réutilise la correspondance statut HTTP -> raison du lecteur Google du plan de mesure
(`_raise_for_status`). Le jeton n'apparaît jamais dans une erreur : les exceptions
httpx (qui portent la requête) sont remplacées, pas chaînées."""

from __future__ import annotations

from typing import Any

import httpx

from app.services.measurement.google_reader import GoogleReadError, _raise_for_status
from app.services.metrics.types import SourceError

_TIMEOUT = httpx.Timeout(30.0)

# Raison -> nouvelle tentative utile ?
RECOVERABLE_REASONS: dict[str, bool] = {
    "token_unavailable": False,
    "permission_or_api_disabled": False,
    "not_found": False,
    # Requête invalide (HTTP 400) : la renvoyer telle quelle échouerait de nouveau.
    "bad_request": False,
    # Échec temporaire du rafraîchissement du jeton (réseau, 5xx) : retenter a du sens.
    "token_refresh_failed": True,
    # Réponse paginée coupée (plafond de pages atteint) : jamais de collecte partielle.
    "truncated": True,
    "quota": True,
    "network": True,
    "api_error": True,
}


async def google_json(
    method: str,
    url: str,
    token: str,
    *,
    json: dict[str, Any] | None = None,
    client: httpx.AsyncClient | None = None,
) -> Any:
    owns = client is None
    http = client or httpx.AsyncClient(timeout=_TIMEOUT)
    try:
        try:
            response = await http.request(
                method, url, json=json, headers={"Authorization": f"Bearer {token}"}
            )
        except httpx.HTTPError:
            raise SourceError("network", recoverable=True) from None
    finally:
        if owns:
            await http.aclose()
    if response.status_code == 400:
        raise SourceError("bad_request", recoverable=False)
    try:
        _raise_for_status(response)
    except GoogleReadError as exc:
        raise SourceError(exc.reason, recoverable=RECOVERABLE_REASONS.get(exc.reason, True)) from None
    try:
        return response.json()
    except ValueError:
        raise SourceError("api_error", recoverable=True) from None
