from datetime import UTC, date, datetime

import httpx
import pytest

from app.models.website import Website
from app.services.metrics.sources.cwv import CwvSource, parse_cwv
from app.services.metrics.sources.probes import ProbeSource
from app.services.metrics.types import DayRange, Observation, SourceError
from app.services.page_fetch import PageSnapshot
from app.services.tls_check import TlsStatus

TODAY = date(2026, 9, 26)
NOW = datetime(2026, 9, 26, 6, 0, tzinfo=UTC)
SITE = Website(domain="exemple.fr", display_name="Exemple", allow_insecure_probe=False)
TODAY_ONLY = DayRange(TODAY, TODAY)


def _payload(*, origin: dict | None = None, score: float | None = 0.72) -> dict:
    payload: dict = {"lighthouseResult": {"categories": {"performance": {"score": score}}}}
    if origin is not None:
        payload["originLoadingExperience"] = {"metrics": origin}
    # Données de la page seule : jamais lues (la valeur terrain est celle de l'origine).
    payload["loadingExperience"] = {
        "metrics": {"LARGEST_CONTENTFUL_PAINT_MS": {"percentile": 99999}}
    }
    return payload


_ORIGIN = {
    "LARGEST_CONTENTFUL_PAINT_MS": {"percentile": 2300},
    "INTERACTION_TO_NEXT_PAINT": {"percentile": 180},
    "CUMULATIVE_LAYOUT_SHIFT_SCORE": {"percentile": 5},
}


def test_parse_cwv_reads_origin_field_data_and_lab_score() -> None:
    observations = parse_cwv(_payload(origin=_ORIGIN), day=TODAY)
    assert {o.metric: o.value for o in observations} == {
        "lcp_p75_ms": 2300.0,
        "inp_p75_ms": 180.0,
        "cls_p75": 0.05,
        "performance_score": 72.0,
    }


def test_parse_cwv_without_field_data_gives_no_field_observation() -> None:
    observations = parse_cwv(_payload(origin=None, score=None), day=TODAY)
    assert observations == []


def test_parse_cwv_never_fills_field_data_with_lab_or_zero() -> None:
    observations = parse_cwv(_payload(origin=None, score=0.5), day=TODAY)
    assert [o.metric for o in observations] == ["performance_score"]


def test_parse_cwv_observations_are_unique_per_metric_and_day() -> None:
    # Le stockage additionne les doublons de clé : chaque (métrique, jour, dims) une fois.
    origin = {**_ORIGIN, "EXPERIMENTAL_INTERACTION_TO_NEXT_PAINT": {"percentile": 999}}
    observations = parse_cwv(_payload(origin=origin), day=TODAY)
    keys = [(o.metric, o.day, tuple(sorted(o.dims.items()))) for o in observations]
    assert len(keys) == len(set(keys)) == 4
    assert {o.metric: o.value for o in observations}["inp_p75_ms"] == 180.0


def test_parse_cwv_rejects_a_non_object() -> None:
    with pytest.raises(SourceError) as excinfo:
        parse_cwv(["pas", "un", "objet"], day=TODAY)
    assert excinfo.value.reason == "api_error" and excinfo.value.recoverable


def test_parse_cwv_rejects_a_non_finite_percentile() -> None:
    origin = {"LARGEST_CONTENTFUL_PAINT_MS": {"percentile": float("nan")}}
    with pytest.raises(SourceError) as excinfo:
        parse_cwv(_payload(origin=origin), day=TODAY)
    assert excinfo.value.reason == "api_error" and excinfo.value.recoverable


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_cwv_source_calls_pagespeed_for_the_origin_with_the_key() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=_payload(origin=_ORIGIN))

    source = CwvSource(api_key="cle", client=_client(handler), today=lambda: TODAY)
    observations = await source.collect(SITE, TODAY_ONLY)
    assert len(seen) == 1
    params = seen[0].url.params
    assert params["url"] == "https://exemple.fr" and params["strategy"] == "mobile"
    assert params["key"] == "cle"
    assert all(o.day == TODAY for o in observations) and len(observations) == 4
    assert "cle" not in repr(observations)


async def test_cwv_source_without_key_sends_none() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=_payload(origin=_ORIGIN))

    source = CwvSource(api_key=None, client=_client(handler), today=lambda: TODAY)
    await source.collect(SITE, TODAY_ONLY)
    assert "key" not in seen[0].url.params


async def test_cwv_source_skips_a_window_without_today() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("aucun appel attendu")

    source = CwvSource(api_key=None, client=_client(handler), today=lambda: TODAY)
    assert await source.collect(SITE, DayRange(date(2026, 9, 1), date(2026, 9, 20))) == []


@pytest.mark.parametrize(
    ("status", "reason", "recoverable"),
    [
        (429, "quota", True),
        (400, "site_unreachable", False),
        (401, "permission_or_api_disabled", False),
        (403, "permission_or_api_disabled", False),
        (500, "api_error", True),
        (404, "api_error", False),
    ],
)
async def test_cwv_http_errors_are_classified(status: int, reason: str, recoverable: bool) -> None:
    source = CwvSource(
        api_key="cle",
        client=_client(lambda request: httpx.Response(status, json={})),
        today=lambda: TODAY,
    )
    with pytest.raises(SourceError) as excinfo:
        await source.collect(SITE, TODAY_ONLY)
    assert (excinfo.value.reason, excinfo.value.recoverable) == (reason, recoverable)


async def test_cwv_invalid_json_is_a_recoverable_api_error() -> None:
    source = CwvSource(
        api_key="cle",
        client=_client(lambda request: httpx.Response(200, content=b"<html>")),
        today=lambda: TODAY,
    )
    with pytest.raises(SourceError) as excinfo:
        await source.collect(SITE, TODAY_ONLY)
    assert excinfo.value.reason == "api_error" and excinfo.value.recoverable


async def test_cwv_network_error_never_carries_the_key() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom", request=request)

    source = CwvSource(api_key="cle-secrete", client=_client(handler), today=lambda: TODAY)
    with pytest.raises(SourceError) as excinfo:
        await source.collect(SITE, TODAY_ONLY)
    assert excinfo.value.reason == "network"
    assert excinfo.value.__cause__ is None and excinfo.value.__suppress_context__
    assert "cle-secrete" not in str(excinfo.value)


def _tls(status: str, days: int | None) -> TlsStatus:
    return TlsStatus(host="exemple.fr", status=status, checked_at=NOW, days_remaining=days)


def _page(status: int) -> PageSnapshot:
    return PageSnapshot(
        url="https://exemple.fr",
        final_url="https://exemple.fr/",
        status=status,
        html="<html></html>",
        headers={"content-type": "text/html"},
        redirected=False,
        history=(),
    )


def _probe(tls: TlsStatus, page: PageSnapshot | None, calls: list | None = None) -> ProbeSource:
    async def tls_checker(domain: str) -> TlsStatus:
        return tls

    async def page_fetcher(url: str, *, allow_insecure: bool = False) -> PageSnapshot | None:
        if calls is not None:
            calls.append((url, allow_insecure))
        return page

    return ProbeSource(tls_checker=tls_checker, page_fetcher=page_fetcher, today=lambda: TODAY)


async def test_probes_observe_certificate_and_availability() -> None:
    calls: list = []
    observations = await _probe(_tls("valid", 45), _page(200), calls).collect(SITE, TODAY_ONLY)
    assert observations == [
        Observation("tls_days_remaining", TODAY, 45.0),
        Observation("page_up", TODAY, 1.0),
    ]
    assert calls == [("https://exemple.fr", False)]


async def test_probes_forward_allow_insecure_probe() -> None:
    calls: list = []
    site = Website(domain="exemple.fr", display_name="Exemple", allow_insecure_probe=True)
    await _probe(_tls("valid", 45), _page(200), calls).collect(site, TODAY_ONLY)
    assert calls == [("https://exemple.fr", True)]


async def test_probes_skip_a_window_without_today() -> None:
    calls: list = []
    probe = _probe(_tls("valid", 45), _page(200), calls)
    assert await probe.collect(SITE, DayRange(date(2026, 9, 1), date(2026, 9, 20))) == []
    assert calls == []


async def test_an_expired_certificate_and_a_server_error_are_real_observations() -> None:
    observations = await _probe(_tls("expired", -3), _page(503)).collect(SITE, TODAY_ONLY)
    assert {o.metric: o.value for o in observations} == {
        "tls_days_remaining": -3.0,
        "page_up": 0.0,
    }


async def test_nothing_observable_is_a_recoverable_error() -> None:
    with pytest.raises(SourceError) as excinfo:
        await _probe(_tls("unreachable", None), None).collect(SITE, TODAY_ONLY)
    assert excinfo.value.reason == "unreachable" and excinfo.value.recoverable


async def test_a_partial_probe_keeps_what_was_observed() -> None:
    observations = await _probe(_tls("unreachable", None), _page(200)).collect(SITE, TODAY_ONLY)
    assert observations == [Observation("page_up", TODAY, 1.0)]
