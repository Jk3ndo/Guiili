"""Client Search Console — parseur + appels HTTP mockes (zero reseau)."""

import httpx

from app.services.gsc import (
    _relative_path,
    fetch_search_analytics,
    parse_search_analytics,
)

_QUERY_HOST = "https://www.googleapis.com/webmasters/v3/sites/"

_PAYLOAD = {
    "rows": [
        {
            "keys": ["https://boutique-verte.fr/collections/homme"],
            "clicks": 320,
            "impressions": 8400.0,
            "ctr": 0.038,
        },
        {
            "keys": ["https://boutique-verte.fr/blog/guide-coton?utm=x"],
            "clicks": 210,
            "impressions": 3100.0,
        },
        {
            "keys": ["https://boutique-verte.fr/produits/edition"],
            "clicks": 5,
            "impressions": 5200.0,
        },
        {"keys": ["https://boutique-verte.fr/"], "clicks": 140, "impressions": 2000.0},
    ]
}


def _transport(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def test_relative_path() -> None:
    assert _relative_path("https://x.fr/collections/homme?u=1") == "/collections/homme"
    assert _relative_path("https://x.fr/") == "/"
    assert _relative_path("/already/relative") == "/already/relative"


def test_parse_builds_sorted_samples_and_score() -> None:
    signals = parse_search_analytics(_PAYLOAD)

    assert signals.degraded is False
    assert signals.valid_pages == 4
    # tri par clics decroissant (320, 210, 140, 5), chemins relatifs
    assert [s.path for s in signals.sample_urls] == [
        "/collections/homme",
        "/blog/guide-coton",
        "/",
        "/produits/edition",
    ]
    top = signals.sample_urls[0]
    assert (top.clicks, top.impressions, top.status) == (320, 8400, "Indexée")
    assert signals.score > 0


def test_parse_caps_at_ten_urls() -> None:
    payload = {
        "rows": [
            {"keys": [f"https://x.fr/p{i}"], "clicks": 100 - i, "impressions": 1000}
            for i in range(25)
        ]
    }
    assert len(parse_search_analytics(payload).sample_urls) == 10
    assert parse_search_analytics(payload).valid_pages == 25


def test_parse_empty_is_neutral_not_degraded() -> None:
    signals = parse_search_analytics({"rows": []})
    assert signals.score == 0
    assert signals.degraded is False
    assert signals.sample_urls == ()


async def test_fetch_builds_query_request() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("Authorization")
        seen["body"] = request.read().decode()
        return httpx.Response(200, json=_PAYLOAD)

    async with _transport(handler) as client:
        signals = await fetch_search_analytics(
            "tok-123", "sc-domain:boutique-verte.fr", days=30, client=client
        )

    assert str(seen["url"]).startswith(_QUERY_HOST)
    assert "searchAnalytics/query" in str(seen["url"])
    assert seen["auth"] == "Bearer tok-123"
    assert '"dimensions":["page"]' in str(seen["body"])
    assert '"startDate"' in str(seen["body"])
    assert signals.sample_urls[0].path == "/collections/homme"


async def test_fetch_degrades_on_401() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": {"message": "invalid credentials"}})

    async with _transport(handler) as client:
        signals = await fetch_search_analytics("dead", "sc-domain:x.fr", client=client)

    assert signals.degraded is True
    assert signals.score == 0
    assert signals.connection_stale_days == 30


async def test_fetch_degrades_on_403_quota() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"error": {"message": "quota exceeded"}})

    async with _transport(handler) as client:
        signals = await fetch_search_analytics("tok", "sc-domain:x.fr", client=client)

    assert signals.degraded is True


async def test_fetch_degrades_on_transport_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route")

    async with _transport(handler) as client:
        signals = await fetch_search_analytics("tok", "sc-domain:x.fr", client=client)

    assert signals.degraded is True
