"""Doubles pour l'auto-liaison : aucun appel réseau."""

from __future__ import annotations

from app.services.google_oauth.base import DiscoveredResources, GoogleTokenResponse
from app.services.measurement.google_reader import GoogleReadError


class FakeOAuth:
    """Duck-typing de `GoogleOAuthClient` : seules les deux méthodes utilisées."""

    def __init__(self, resources: DiscoveredResources) -> None:
        self._resources = resources
        self.discover_calls = 0

    async def refresh_access_token(self, *, refresh_token: str) -> GoogleTokenResponse:
        return GoogleTokenResponse(access_token="tok", expires_in=3599, scopes=("openid",))

    async def discover_resources(self, *, access_token: str) -> DiscoveredResources:
        self.discover_calls += 1
        return self._resources


def fake_stream_hosts(mapping: dict[str, set[str]], *, failing: frozenset[str] = frozenset()):
    """Fabrique un `StreamHostsFetcher` ; `calls` liste les propriétés interrogées."""
    calls: list[str] = []

    async def fetch(token: str, property_id: str) -> set[str]:
        calls.append(property_id)
        if property_id in failing:
            raise GoogleReadError("permission_or_api_disabled")
        return set(mapping.get(property_id, set()))

    fetch.calls = calls  # type: ignore[attr-defined]
    return fetch
