# backend/app/services/measurement/fetch.py
from __future__ import annotations

from collections.abc import Awaitable, Callable

import httpx

from app.services.page_fetch import PageSnapshot, fetch_page

PageFetcher = Callable[..., Awaitable[PageSnapshot | None]]


async def fetch_page_safe(url: str, *, allow_insecure: bool = False) -> PageSnapshot | None:
    """`fetch_page` qui ne lève jamais : `None` si le site est injoignable."""
    try:
        return await fetch_page(url, allow_insecure=allow_insecure)
    except (httpx.HTTPError, httpx.InvalidURL):
        return None
