"""Parseur + client PageSpeed Insights — fixtures JSON, zéro appel réseau."""

import json
from pathlib import Path

import httpx
import pytest

from app.services.audit_probe import CwvSignals, RealAuditProbe
from app.services.pagespeed import PAGESPEED_URL, fetch_pagespeed, parse_pagespeed

_FIXTURE = json.loads(
    (Path(__file__).parent / "fixtures" / "pagespeed_mobile.json").read_text("utf-8")
)


def test_parse_prefers_field_data() -> None:
    result = parse_pagespeed(_FIXTURE)
    assert result["field_data"] is True
    assert result["lcp_ms"] == 3400  # CrUX terrain, pas les 3812 du labo
    assert result["inp_ms"] == 310
    assert result["cls"] == pytest.approx(0.18)
    assert result["score"] == 42


def test_parse_extracts_diagnostics() -> None:
    result = parse_pagespeed(_FIXTURE)
    assert "hero-banner.jpg" in result["heavy_assets"]
    assert "collection-2026-large.png" in result["heavy_assets"]
    assert "theme.css" in result["blocking_scripts"]
    assert set(result["third_party_scripts"]) == {"Google Tag Manager", "Hotjar"}
    assert result["js_execution_ms"] == 2100
    assert result["total_blocking_time_ms"] == 640
    assert result["lcp_element"] and "hero-image" in result["lcp_element"]
    # CwvSignals accepte le dict tel quel
    assert isinstance(CwvSignals(**result), CwvSignals)


def test_parse_falls_back_to_lab_without_field_data() -> None:
    lab_only = {"lighthouseResult": _FIXTURE["lighthouseResult"]}
    result = parse_pagespeed(lab_only)
    assert result["field_data"] is False
    assert result["lcp_ms"] == 3812  # numericValue 3812.5 arrondi (banker's rounding)
    assert result["inp_ms"] == 290
    assert result["cls"] == pytest.approx(0.214)


def test_parse_empty_payload_is_degraded() -> None:
    result = parse_pagespeed({})
    assert result == {
        "score": 0,
        "lcp_ms": 0,
        "inp_ms": 0,
        "cls": 0.0,
        "heavy_assets": (),
        "blocking_scripts": (),
        "third_party_scripts": (),
        "js_execution_ms": 0,
        "total_blocking_time_ms": 0,
        "lcp_element": None,
        "field_data": False,
    }


def _transport(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_fetch_builds_mobile_request_with_key() -> None:
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(dict(request.url.params))
        assert str(request.url).startswith(PAGESPEED_URL)
        return httpx.Response(200, json=_FIXTURE)

    async with _transport(handler) as client:
        result = await fetch_pagespeed("boutique-verte.fr", api_key="secret-key", client=client)

    assert seen["strategy"] == "mobile"
    assert seen["url"] == "https://boutique-verte.fr"
    assert seen["key"] == "secret-key"
    assert result["lcp_ms"] == 3400


async def test_fetch_keyless_omits_key_param() -> None:
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(dict(request.url.params))
        return httpx.Response(200, json=_FIXTURE)

    async with _transport(handler) as client:
        await fetch_pagespeed("x.test", client=client)
    assert "key" not in seen


async def test_fetch_degrades_on_http_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"error": {"message": "quota"}})

    async with _transport(handler) as client:
        result = await fetch_pagespeed("x.test", client=client)
    assert result == {"score": 0, "field_data": False}


async def test_fetch_degrades_on_transport_failure() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route")

    async with _transport(handler) as client:
        result = await fetch_pagespeed("x.test", client=client)
    assert result == {"score": 0, "field_data": False}


async def test_real_probe_returns_probe_data_with_cwv_from_pagespeed() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_FIXTURE)

    async with _transport(handler) as client:
        probe = RealAuditProbe(client=client)
        data = await probe.collect(domain="boutique-verte.fr", stack=None)  # type: ignore[arg-type]

    assert data.cwv.lcp_ms == 3400
    assert data.cwv.field_data is True
    assert "hero-banner.jpg" in data.cwv.heavy_assets
    # GA4 / GSC neutres jusqu'a P3
    assert data.ga4.score == 0
    assert data.gsc.score == 0


async def test_real_probe_degraded_still_returns_probe_data() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("offline")

    async with _transport(handler) as client:
        data = await RealAuditProbe(client=client).collect(
            domain="x.test",
            stack=None,  # type: ignore[arg-type]
        )
    assert data.cwv.score == 0
    assert data.cwv.field_data is False
