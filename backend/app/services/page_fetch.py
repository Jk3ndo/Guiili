"""Fetch HTTP leger partage : un GET, en-tetes aplaties, redirections tracees.

Sert la detection de stack et le check GTM. `fetch_page` peut lever
`httpx.HTTPError` — les appelants (ex. `check_gtm`) decident quoi en faire.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

import httpx

_TIMEOUT = httpx.Timeout(8.0)
_MAX_BYTES = 400_000
_UA = "ControlCenterBot/1.0"


@dataclass(frozen=True, slots=True)
class PageSnapshot:
    url: str
    final_url: str
    status: int
    html: str
    headers: Mapping[str, str]
    redirected: bool
    history: tuple[tuple[int, str], ...]


async def fetch_page(
    url: str,
    *,
    allow_insecure: bool = False,
    client: httpx.AsyncClient | None = None,
) -> PageSnapshot:
    owns_client = client is None
    http = client or httpx.AsyncClient(
        timeout=_TIMEOUT,
        follow_redirects=True,
        headers={"User-Agent": _UA},
        verify=not allow_insecure,
    )
    try:
        response = await http.get(url)
    finally:
        if owns_client:
            await http.aclose()

    history = tuple(
        (hop.status_code, hop.headers.get("location", "")) for hop in response.history
    )
    return PageSnapshot(
        url=url,
        final_url=str(response.url),
        status=response.status_code,
        html=response.text[:_MAX_BYTES],
        headers={k.lower(): v for k, v in response.headers.items()},
        redirected=bool(response.history),
        history=history,
    )
