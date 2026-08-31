"""Client GA4 Data API — parseur + appels HTTP mockes (zero reseau)."""

import httpx

from app.services.ga4 import _property_number, fetch_event_metrics, parse_run_report


def _row(name: str, count: float, revenue: float = 0.0, value: float = 0.0) -> dict:
    return {
        "dimensionValues": [{"value": name}],
        "metricValues": [
            {"value": str(count)},
            {"value": str(revenue)},
            {"value": str(value)},
        ],
    }


def _transport(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def test_property_number() -> None:
    assert _property_number("properties/447213908") == "447213908"
    assert _property_number("447213908") == "447213908"


def test_parse_healthy_stream() -> None:
    payload = {
        "rows": [
            _row("page_view", 48000),
            _row("purchase", 400, revenue=18250.0),
            _row("generate_lead", 60),
        ]
    }
    signals = parse_run_report(payload)
    assert signals.score == 90
    assert signals.purchase_missing_params == ()
    assert signals.missing_events == ()
    assert signals.degraded is False


def test_parse_detects_purchase_with_zero_revenue() -> None:
    payload = {
        "rows": [
            _row("page_view", 48000),
            _row("purchase", 400, revenue=0.0, value=0.0),
        ]
    }
    signals = parse_run_report(payload)
    assert signals.purchase_missing_params == ("value", "currency")
    assert signals.score == 60


def test_parse_flags_missing_generate_lead_when_site_has_traffic() -> None:
    payload = {"rows": [_row("page_view", 12000), _row("purchase", 5, revenue=900.0)]}
    signals = parse_run_report(payload)
    assert signals.missing_events == ("generate_lead",)


def test_parse_no_page_view_is_low_score() -> None:
    signals = parse_run_report({"rows": [_row("scroll", 200)]})
    assert signals.score == 15


async def test_fetch_builds_run_report_request() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("Authorization")
        seen["body"] = request.read().decode()
        return httpx.Response(
            200, json={"rows": [_row("page_view", 100), _row("generate_lead", 4)]}
        )

    async with _transport(handler) as client:
        signals = await fetch_event_metrics(
            "tok-xyz", "properties/447213908", days=30, client=client
        )

    assert str(seen["url"]).endswith("/properties/447213908:runReport")
    assert seen["auth"] == "Bearer tok-xyz"
    assert '"eventName"' in str(seen["body"])
    assert '"30daysAgo"' in str(seen["body"])
    assert signals.score == 90
    assert signals.degraded is False


async def test_fetch_degrades_on_401() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": {"message": "revoked"}})

    async with _transport(handler) as client:
        signals = await fetch_event_metrics("dead", "properties/1", client=client)

    assert signals.degraded is True
    assert signals.score == 0


async def test_fetch_degrades_on_403_quota() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"error": {"message": "quota"}})

    async with _transport(handler) as client:
        signals = await fetch_event_metrics("tok", "properties/1", client=client)

    assert signals.degraded is True


async def test_fetch_degrades_on_transport_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("offline")

    async with _transport(handler) as client:
        signals = await fetch_event_metrics("tok", "properties/1", client=client)

    assert signals.degraded is True
