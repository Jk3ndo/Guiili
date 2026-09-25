"""Lectures Google pour le plan de mesure (GA4 Data, GA4 Admin, Search Console).

Lecture seule, scopes déjà demandés. Toute erreur devient une `GoogleReadError` avec
une `reason` stable : le moteur de vérification la traduit en « non vérifiable », il
ne l'interprète jamais comme « manquant ».
"""

from __future__ import annotations

from typing import Any, Protocol
from urllib.parse import quote, urlsplit

import httpx

from app.services.ga4 import _RUN_REPORT_URL, _metric, _property_number

_ADMIN = "https://analyticsadmin.googleapis.com/v1beta/properties/{pid}"
_SITEMAPS = "https://searchconsole.googleapis.com/webmasters/v3/sites/{site}/sitemaps"
_TIMEOUT = httpx.Timeout(20.0)


class GoogleReadError(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class GoogleReader(Protocol):
    gsc_state: str

    async def event_stats(self) -> dict[str, dict[str, float]]: ...

    async def key_events(self) -> list[dict[str, Any]]: ...

    async def ads_links_count(self) -> int: ...

    async def measurement_id(self) -> str | None: ...

    async def sitemaps_count(self) -> int: ...


def parse_event_stats(payload: Any) -> dict[str, dict[str, float]]:
    rows = payload.get("rows", []) if isinstance(payload, dict) else []
    stats: dict[str, dict[str, float]] = {}
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
        stats[name] = {
            "count": _metric(metrics, 0),
            "revenue": _metric(metrics, 1),
            "value": _metric(metrics, 2),
        }
    return stats


def _raise_for_status(response: httpx.Response) -> None:
    code = response.status_code
    if code < 400:
        return
    if code == 401:
        raise GoogleReadError("token_unavailable")
    if code == 403:
        raise GoogleReadError("permission_or_api_disabled")
    if code == 404:
        raise GoogleReadError("not_found")
    if code == 429:
        raise GoogleReadError("quota")
    raise GoogleReadError("api_error")


class HttpGoogleReader:
    def __init__(
        self,
        *,
        ga4_token: str | None,
        ga4_property: str | None,
        gsc_token: str | None,
        gsc_site: str | None,
        gsc_state: str,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.ga4_token = ga4_token
        self.ga4_property = ga4_property
        self.gsc_token = gsc_token
        self.gsc_site = gsc_site
        self.gsc_state = gsc_state
        self._client = client

    # -- helpers ------------------------------------------------------------
    def _ga4(self) -> tuple[str, str]:
        if not self.ga4_property:
            raise GoogleReadError("ga4_not_connected")
        if not self.ga4_token:
            raise GoogleReadError("token_unavailable")
        return self.ga4_token, _property_number(self.ga4_property)

    def _gsc(self) -> tuple[str, str]:
        if not self.gsc_site:
            raise GoogleReadError("gsc_not_connected")
        if not self.gsc_token:
            raise GoogleReadError("token_unavailable")
        return self.gsc_token, self.gsc_site

    async def _request(
        self, method: str, url: str, token: str, *, json: dict[str, Any] | None = None
    ) -> Any:
        owns = self._client is None
        http = self._client or httpx.AsyncClient(timeout=_TIMEOUT)
        try:
            response = await http.request(
                method, url, json=json, headers={"Authorization": f"Bearer {token}"}
            )
        except httpx.HTTPError as exc:
            raise GoogleReadError("network") from exc
        finally:
            if owns:
                await http.aclose()
        _raise_for_status(response)
        try:
            return response.json()
        except ValueError as exc:
            raise GoogleReadError("api_error") from exc

    # -- lectures -----------------------------------------------------------
    async def event_stats(self) -> dict[str, dict[str, float]]:
        token, pid = self._ga4()
        body = {
            "dateRanges": [{"startDate": "30daysAgo", "endDate": "today"}],
            "dimensions": [{"name": "eventName"}],
            "metrics": [
                {"name": "eventCount"},
                {"name": "totalRevenue"},
                {"name": "eventValue"},
            ],
        }
        payload = await self._request("POST", _RUN_REPORT_URL.format(pid=pid), token, json=body)
        return parse_event_stats(payload)

    async def key_events(self) -> list[dict[str, Any]]:
        token, pid = self._ga4()
        payload = await self._request("GET", _ADMIN.format(pid=pid) + "/keyEvents", token)
        events = payload.get("keyEvents", []) if isinstance(payload, dict) else []
        return [event for event in events if isinstance(event, dict)]

    async def ads_links_count(self) -> int:
        token, pid = self._ga4()
        payload = await self._request("GET", _ADMIN.format(pid=pid) + "/googleAdsLinks", token)
        links = payload.get("googleAdsLinks", []) if isinstance(payload, dict) else []
        return len(links)

    async def measurement_id(self) -> str | None:
        token, pid = self._ga4()
        payload = await self._request("GET", _ADMIN.format(pid=pid) + "/dataStreams", token)
        streams = payload.get("dataStreams", []) if isinstance(payload, dict) else []
        for stream in streams:
            if not isinstance(stream, dict) or stream.get("type") != "WEB_DATA_STREAM":
                continue
            web = stream.get("webStreamData") or {}
            measurement_id = web.get("measurementId") if isinstance(web, dict) else None
            if isinstance(measurement_id, str) and measurement_id:
                return measurement_id
        return None

    async def sitemaps_count(self) -> int:
        token, site = self._gsc()
        url = _SITEMAPS.format(site=quote(site, safe=""))
        payload = await self._request("GET", url, token)
        sitemaps = payload.get("sitemap", []) if isinstance(payload, dict) else []
        return len(sitemaps)


async def web_stream_hosts(
    token: str, property_id: str, *, client: httpx.AsyncClient | None = None
) -> set[str]:
    """Noms d'hôte des flux web d'une propriété GA4 (sert à l'auto-liaison au domaine)."""
    reader = HttpGoogleReader(
        ga4_token=token,
        ga4_property=property_id,
        gsc_token=None,
        gsc_site=None,
        gsc_state="not_linked",
        client=client,
    )
    pid = _property_number(property_id)
    payload = await reader._request("GET", _ADMIN.format(pid=pid) + "/dataStreams", token)
    streams = payload.get("dataStreams", []) if isinstance(payload, dict) else []
    hosts: set[str] = set()
    for stream in streams:
        if not isinstance(stream, dict) or stream.get("type") != "WEB_DATA_STREAM":
            continue
        web = stream.get("webStreamData") or {}
        uri = web.get("defaultUri") if isinstance(web, dict) else None
        if isinstance(uri, str) and uri:
            host = urlsplit(uri if "//" in uri else f"//{uri}").hostname
            if host:
                hosts.add(host.lower())
    return hosts
