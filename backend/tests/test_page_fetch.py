"""fetch_page : un GET, redirections tracees, corps tronque, jamais de reseau reel."""

import httpx
import pytest

from app.services.page_fetch import fetch_page

_HTML = "<html><head><title>ok</title></head><body>hi</body></html>"


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=True)


async def test_returns_snapshot_with_lowercased_headers() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        _ = request
        return httpx.Response(200, html=_HTML, headers={"Content-Type": "text/html", "X-Foo": "Bar"})

    snap = await fetch_page("https://example.com", client=_client(handler))

    assert snap.status == 200
    assert snap.final_url == "https://example.com"
    assert snap.redirected is False
    assert snap.history == ()
    assert snap.headers["content-type"] == "text/html"
    assert snap.headers["x-foo"] == "Bar"
    assert "<title>ok</title>" in snap.html


async def test_tracks_redirect_history() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/":
            return httpx.Response(301, headers={"Location": "https://example.com/home"})
        return httpx.Response(200, html=_HTML, headers={"Content-Type": "text/html"})

    snap = await fetch_page("https://example.com/", client=_client(handler))

    assert snap.redirected is True
    assert snap.final_url == "https://example.com/home"
    assert snap.history == ((301, "https://example.com/home"),)


async def test_truncates_body() -> None:
    big = "<html><body>" + "a" * 500_000 + "</body></html>"

    def handler(request: httpx.Request) -> httpx.Response:
        _ = request
        return httpx.Response(200, html=big, headers={"Content-Type": "text/html"})

    snap = await fetch_page("https://example.com", client=_client(handler))
    assert len(snap.html) <= 400_000


async def test_network_error_raises_httpx_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        _ = request
        raise httpx.ConnectError("boom")

    with pytest.raises(httpx.HTTPError):
        await fetch_page("https://example.com", client=_client(handler))
