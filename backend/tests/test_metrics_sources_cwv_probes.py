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


def _payload(*, origin: dict | None = None, score: object = 0.72) -> dict:
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


def test_parse_cwv_requires_the_lighthouse_block() -> None:
    # Un 200 sans bloc laboratoire est une réponse tronquée ou étrangère : jamais « [] ».
    payloads: list[object] = [
        {},
        {"originLoadingExperience": {"metrics": _ORIGIN}},
        {"lighthouseResult": None},
        {"lighthouseResult": []},
    ]
    for payload in payloads:
        with pytest.raises(SourceError) as excinfo:
            parse_cwv(payload, day=TODAY)
        assert excinfo.value.reason == "api_error" and excinfo.value.recoverable


@pytest.mark.parametrize(
    "percentile",
    [-5, -0.1, True, False, "2300", None, float("inf"), float("nan"), [2300]],
)
def test_parse_cwv_rejects_an_invalid_present_percentile(percentile: object) -> None:
    origin = {"LARGEST_CONTENTFUL_PAINT_MS": {"percentile": percentile}}
    with pytest.raises(SourceError) as excinfo:
        parse_cwv(_payload(origin=origin), day=TODAY)
    assert excinfo.value.reason == "api_error" and excinfo.value.recoverable


@pytest.mark.parametrize("entry", [None, 2300, "x", [1]])
def test_parse_cwv_rejects_a_metric_entry_that_is_not_an_object(entry: object) -> None:
    with pytest.raises(SourceError) as excinfo:
        parse_cwv(_payload(origin={"INTERACTION_TO_NEXT_PAINT": entry}), day=TODAY)
    assert excinfo.value.reason == "api_error" and excinfo.value.recoverable


@pytest.mark.parametrize("section", [None, "x", 3, []])
def test_parse_cwv_rejects_a_present_section_of_the_wrong_type(section: object) -> None:
    payloads: list[dict] = [
        {**_payload(), "originLoadingExperience": section},
        {**_payload(), "originLoadingExperience": {"metrics": section}},
        {"lighthouseResult": {"categories": section}},
        {"lighthouseResult": {"categories": {"performance": section}}},
    ]
    for payload in payloads:
        with pytest.raises(SourceError) as excinfo:
            parse_cwv(payload, day=TODAY)
        assert excinfo.value.reason == "api_error" and excinfo.value.recoverable


@pytest.mark.parametrize("score", [True, "0.7", -0.1, 1.5, float("nan"), float("inf"), [0.5]])
def test_parse_cwv_rejects_a_present_invalid_score(score: object) -> None:
    with pytest.raises(SourceError) as excinfo:
        parse_cwv(_payload(origin=_ORIGIN, score=score), day=TODAY)
    assert excinfo.value.reason == "api_error" and excinfo.value.recoverable


@pytest.mark.parametrize("code", ["NO_FCP", "PROTOCOL_TIMEOUT", "ERRORED_DOCUMENT_REQUEST"])
def test_parse_cwv_a_lighthouse_runtime_error_is_site_unreachable(code: str) -> None:
    # 200 avec `score: null` ET une origine trop petite : sans ce contrôle, `[]` serait
    # renvoyé silencieusement alors que Lighthouse dit explicitement avoir échoué.
    payload = {"lighthouseResult": {"runtimeError": {"code": code, "message": "x"}}}
    with pytest.raises(SourceError) as excinfo:
        parse_cwv(payload, day=TODAY)
    assert (excinfo.value.reason, excinfo.value.recoverable) == ("site_unreachable", False)


def test_parse_cwv_runtime_error_no_error_is_not_a_failure() -> None:
    # Certaines réponses portent `runtimeError: {"code": "NO_ERROR"}` : ce n'est pas une
    # erreur, juste l'absence explicite d'erreur.
    payload = _payload(origin=_ORIGIN)
    payload["lighthouseResult"]["runtimeError"] = {"code": "NO_ERROR"}
    observations = parse_cwv(payload, day=TODAY)
    assert {o.metric for o in observations} == {"lcp_p75_ms", "inp_p75_ms", "cls_p75", "performance_score"}


@pytest.mark.parametrize("runtime_error", [None, "x", 3, []])
def test_parse_cwv_rejects_a_runtime_error_of_the_wrong_type(runtime_error: object) -> None:
    payload = {"lighthouseResult": {"runtimeError": runtime_error}}
    if runtime_error is None:
        # `None` explicite est traité comme absent (clé présente mais vide) : légitime.
        assert parse_cwv(payload, day=TODAY) == []
        return
    with pytest.raises(SourceError) as excinfo:
        parse_cwv(payload, day=TODAY)
    assert excinfo.value.reason == "api_error" and excinfo.value.recoverable


def test_parse_cwv_absent_keys_are_legitimately_no_data() -> None:
    # Origine trop petite : Google ne renvoie ni `metrics` ni, ici, de catégories.
    assert parse_cwv({"lighthouseResult": {}}, day=TODAY) == []
    payload = {"lighthouseResult": {}, "originLoadingExperience": {"initial_url": "x"}}
    assert parse_cwv(payload, day=TODAY) == []
    # Une seule métrique terrain présente : les autres sont simplement absentes.
    payload = _payload(origin={"LARGEST_CONTENTFUL_PAINT_MS": {"percentile": 0}}, score=0.0)
    assert {o.metric: o.value for o in parse_cwv(payload, day=TODAY)} == {
        "lcp_p75_ms": 0.0,
        "performance_score": 0.0,
    }


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_cwv_source_calls_pagespeed_for_the_origin_with_the_key_in_a_header() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=_payload(origin=_ORIGIN))

    source = CwvSource(api_key="cle", client=_client(handler), today=lambda: TODAY)
    observations = await source.collect(SITE, TODAY_ONLY)
    assert len(seen) == 1
    params = seen[0].url.params
    assert params["url"] == "https://exemple.fr" and params["strategy"] == "mobile"
    # La clé voyage en en-tête, jamais dans l'URL.
    assert "key" not in params and "cle" not in str(seen[0].url)
    assert seen[0].headers["X-Goog-Api-Key"] == "cle"
    assert all(o.day == TODAY for o in observations) and len(observations) == 4
    assert "cle" not in repr(observations)


async def test_cwv_source_without_key_sends_none() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=_payload(origin=_ORIGIN))

    source = CwvSource(api_key=None, client=_client(handler), today=lambda: TODAY)
    await source.collect(SITE, TODAY_ONLY)
    assert "key" not in seen[0].url.params and "x-goog-api-key" not in seen[0].headers


async def test_cwv_source_skips_a_window_without_today() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("aucun appel attendu")

    source = CwvSource(api_key=None, client=_client(handler), today=lambda: TODAY)
    assert await source.collect(SITE, DayRange(date(2026, 9, 1), date(2026, 9, 20))) == []


async def test_cwv_window_bounds_are_inclusive_of_today_only() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=_payload(origin=_ORIGIN))

    source = CwvSource(api_key="cle", client=_client(handler), today=lambda: TODAY)
    # Fin = veille : aujourd'hui n'est pas dans la fenêtre, aucun appel.
    assert await source.collect(SITE, DayRange(date(2026, 9, 20), date(2026, 9, 25))) == []
    assert seen == []
    # Début = aujourd'hui : dans la fenêtre.
    assert len(await source.collect(SITE, DayRange(TODAY, date(2026, 9, 30)))) == 4
    assert len(seen) == 1


# Corps d'erreur réels de PageSpeed / Google APIs (messages raccourcis).
_KEY_INVALID_BODY = {
    "error": {
        "code": 400,
        "message": "API key not valid. Please pass a valid API key.",
        "errors": [{"message": "API key not valid.", "domain": "global", "reason": "badRequest"}],
        "status": "INVALID_ARGUMENT",
        "details": [
            {
                "@type": "type.googleapis.com/google.rpc.ErrorInfo",
                "reason": "API_KEY_INVALID",
                "domain": "googleapis.com",
            }
        ],
    }
}
_KEY_INVALID_LEGACY_BODY = {
    "error": {
        "code": 400,
        "message": "Bad Request",
        "errors": [{"message": "Bad Request", "domain": "usageLimits", "reason": "keyInvalid"}],
    }
}
_SERVICE_DISABLED_BODY = {
    "error": {
        "code": 403,
        "message": "PageSpeed Insights API has not been used in project 1 or it is disabled.",
        "status": "PERMISSION_DENIED",
        "details": [{"@type": "x", "reason": "SERVICE_DISABLED", "domain": "googleapis.com"}],
    }
}
_FAILED_DOCUMENT_BODY = {
    "error": {
        "code": 400,
        "message": "Lighthouse returned error: FAILED_DOCUMENT_REQUEST. Lighthouse was unable "
        "to reliably load the page you requested.",
        "errors": [
            {
                "message": "Lighthouse returned error: FAILED_DOCUMENT_REQUEST.",
                "domain": "lighthouse",
                "reason": "lighthouseError",
            }
        ],
        "status": "INVALID_ARGUMENT",
    }
}
_FAILED_DOCUMENT_REASON_BODY = {
    "error": {
        "code": 500,
        "message": "Lighthouse error",
        "status": "INTERNAL",
        "details": [{"@type": "x", "reason": "FAILED_DOCUMENT_REQUEST"}],
    }
}
_QUOTA_BODY = {
    "error": {
        "code": 429,
        "message": "Quota exceeded for quota metric 'Queries'",
        "status": "RESOURCE_EXHAUSTED",
    }
}
_UNKNOWN_400_BODY = {"error": {"code": 400, "message": "Invalid value at 'strategy'"}}


@pytest.mark.parametrize(
    ("status", "body", "reason", "recoverable"),
    [
        (429, {}, "quota", True),
        (429, _QUOTA_BODY, "quota", True),
        # Ex-test du brief (400 -> site_unreachable) : désormais avec un vrai corps
        # FAILED_DOCUMENT_REQUEST, un 400 quelconque n'est plus « site injoignable ».
        (400, _FAILED_DOCUMENT_BODY, "site_unreachable", False),
        (500, _FAILED_DOCUMENT_REASON_BODY, "site_unreachable", False),
        (400, _KEY_INVALID_BODY, "api_key_rejected", False),
        (400, _KEY_INVALID_LEGACY_BODY, "api_key_rejected", False),
        (403, _SERVICE_DISABLED_BODY, "api_key_rejected", False),
        (401, {}, "api_key_rejected", False),
        (403, {}, "api_key_rejected", False),
        (400, _UNKNOWN_400_BODY, "bad_request", False),
        (400, {}, "bad_request", False),
        (408, {}, "api_error", True),
        (425, {}, "api_error", True),
        (500, {}, "api_error", True),
        (503, {"error": {"code": 503, "status": "UNAVAILABLE"}}, "api_error", True),
        (404, {}, "api_error", False),
    ],
)
async def test_cwv_http_errors_are_classified(
    status: int, body: dict, reason: str, recoverable: bool
) -> None:
    source = CwvSource(
        api_key="cle",
        client=_client(lambda request: httpx.Response(status, json=body)),
        today=lambda: TODAY,
    )
    with pytest.raises(SourceError) as excinfo:
        await source.collect(SITE, TODAY_ONLY)
    assert (excinfo.value.reason, excinfo.value.recoverable) == (reason, recoverable)


@pytest.mark.parametrize(
    ("status", "body"),
    [(400, _KEY_INVALID_BODY), (403, _SERVICE_DISABLED_BODY), (401, {})],
)
async def test_cwv_a_rejected_key_is_never_a_client_side_code(status: int, body: dict) -> None:
    # `site_unreachable` et `permission_or_api_disabled` seront classés « le client peut
    # agir » : une clé invalide (notre configuration) ne doit jamais y tomber.
    source = CwvSource(
        api_key="cle",
        client=_client(lambda request: httpx.Response(status, json=body)),
        today=lambda: TODAY,
    )
    with pytest.raises(SourceError) as excinfo:
        await source.collect(SITE, TODAY_ONLY)
    assert excinfo.value.reason not in {"site_unreachable", "permission_or_api_disabled"}


async def test_cwv_error_never_copies_the_response_body() -> None:
    body = {"error": {"code": 400, "message": "secret-message cle-secrete", "status": "X"}}
    source = CwvSource(
        api_key="cle-secrete",
        client=_client(lambda request: httpx.Response(400, json=body)),
        today=lambda: TODAY,
    )
    with pytest.raises(SourceError) as excinfo:
        await source.collect(SITE, TODAY_ONLY)
    assert "secret" not in str(excinfo.value) and "secret" not in repr(excinfo.value.__dict__)


async def test_cwv_non_json_error_body_is_still_classified() -> None:
    source = CwvSource(
        api_key="cle",
        client=_client(lambda request: httpx.Response(403, content=b"<html>Forbidden</html>")),
        today=lambda: TODAY,
    )
    with pytest.raises(SourceError) as excinfo:
        await source.collect(SITE, TODAY_ONLY)
    assert excinfo.value.reason == "api_key_rejected"


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
        # Une vraie exception httpx porte la requête, donc ses en-têtes (clé comprise).
        raise httpx.ConnectError(f"boom {request.headers['x-goog-api-key']}", request=request)

    source = CwvSource(api_key="cle-secrete", client=_client(handler), today=lambda: TODAY)
    with pytest.raises(SourceError) as excinfo:
        await source.collect(SITE, TODAY_ONLY)
    error = excinfo.value
    assert error.reason == "network" and error.recoverable
    assert error.__cause__ is None and error.__suppress_context__
    assert "cle-secrete" not in str(error) and "cle-secrete" not in repr(error.__dict__)
    assert "cle-secrete" not in repr(error.args)


async def test_cwv_invalid_url_is_a_definitive_bad_request() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.InvalidURL("URL invalide cle-secrete")

    source = CwvSource(api_key="cle-secrete", client=_client(handler), today=lambda: TODAY)
    with pytest.raises(SourceError) as excinfo:
        await source.collect(SITE, TODAY_ONLY)
    assert (excinfo.value.reason, excinfo.value.recoverable) == ("bad_request", False)
    assert excinfo.value.__cause__ is None and "cle-secrete" not in str(excinfo.value)


async def test_cwv_observations_and_logs_never_contain_the_key(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level("DEBUG")
    source = CwvSource(
        api_key="cle-secrete",
        client=_client(lambda request: httpx.Response(200, json=_payload(origin=_ORIGIN))),
        today=lambda: TODAY,
    )
    observations = await source.collect(SITE, TODAY_ONLY)
    assert "cle-secrete" not in repr(observations) and "cle-secrete" not in caplog.text


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


async def test_probes_window_bounds_are_inclusive_of_today_only() -> None:
    calls: list = []
    probe = _probe(_tls("valid", 45), _page(200), calls)
    # Fin = veille : aucune sonde.
    assert await probe.collect(SITE, DayRange(date(2026, 9, 20), date(2026, 9, 25))) == []
    assert calls == []
    # Début = aujourd'hui : dans la fenêtre.
    assert len(await probe.collect(SITE, DayRange(TODAY, date(2026, 9, 30)))) == 2
    assert len(calls) == 1


async def test_an_expired_certificate_and_a_server_error_are_real_observations() -> None:
    observations = await _probe(_tls("expired", -3), _page(503)).collect(SITE, TODAY_ONLY)
    assert {o.metric: o.value for o in observations} == {
        "tls_days_remaining": -3.0,
        "page_up": 0.0,
    }


@pytest.mark.parametrize(
    ("status", "expected"),
    [(200, 1.0), (301, 1.0), (404, 0.0), (410, 0.0), (500, 0.0), (503, 0.0)],
)
async def test_page_up_statuses(status: int, expected: float) -> None:
    observations = await _probe(_tls("valid", 45), _page(status)).collect(SITE, TODAY_ONLY)
    assert Observation("page_up", TODAY, expected) in observations


@pytest.mark.parametrize("status", [401, 403, 429, 400])
async def test_a_blocked_or_inconclusive_answer_omits_page_up(status: int) -> None:
    # Un pare-feu ou un anti-bot ne doit pas passer pour une panne.
    observations = await _probe(_tls("valid", 45), _page(status)).collect(SITE, TODAY_ONLY)
    assert observations == [Observation("tls_days_remaining", TODAY, 45.0)]


async def test_a_blocked_answer_with_no_tls_is_a_recoverable_error() -> None:
    with pytest.raises(SourceError) as excinfo:
        await _probe(_tls("unreachable", None), _page(403)).collect(SITE, TODAY_ONLY)
    assert excinfo.value.reason == "unreachable" and excinfo.value.recoverable


async def test_nothing_observable_is_a_recoverable_error() -> None:
    with pytest.raises(SourceError) as excinfo:
        await _probe(_tls("unreachable", None), None).collect(SITE, TODAY_ONLY)
    assert excinfo.value.reason == "unreachable" and excinfo.value.recoverable


async def test_a_partial_probe_keeps_what_was_observed() -> None:
    observations = await _probe(_tls("unreachable", None), _page(200)).collect(SITE, TODAY_ONLY)
    assert observations == [Observation("page_up", TODAY, 1.0)]


async def test_a_page_fetcher_exception_keeps_the_tls_observation(
    caplog: pytest.LogCaptureFixture,
) -> None:
    async def tls_checker(domain: str) -> TlsStatus:
        return _tls("valid", 45)

    async def page_fetcher(url: str, *, allow_insecure: bool = False) -> PageSnapshot | None:
        raise httpx.InvalidURL("https://exemple.fr/?key=cle-secrete")

    probe = ProbeSource(tls_checker=tls_checker, page_fetcher=page_fetcher, today=lambda: TODAY)
    observations = await probe.collect(SITE, TODAY_ONLY)
    assert observations == [Observation("tls_days_remaining", TODAY, 45.0)]
    assert "cle-secrete" not in caplog.text


async def test_a_tls_checker_exception_keeps_the_page_observation() -> None:
    async def tls_checker(domain: str) -> TlsStatus:
        raise RuntimeError("boom")

    async def page_fetcher(url: str, *, allow_insecure: bool = False) -> PageSnapshot | None:
        return _page(200)

    probe = ProbeSource(tls_checker=tls_checker, page_fetcher=page_fetcher, today=lambda: TODAY)
    assert await probe.collect(SITE, TODAY_ONLY) == [Observation("page_up", TODAY, 1.0)]


async def test_both_probes_raising_is_a_typed_recoverable_error() -> None:
    async def tls_checker(domain: str) -> TlsStatus:
        raise RuntimeError("boom")

    async def page_fetcher(url: str, *, allow_insecure: bool = False) -> PageSnapshot | None:
        raise OSError("boom")

    probe = ProbeSource(tls_checker=tls_checker, page_fetcher=page_fetcher, today=lambda: TODAY)
    with pytest.raises(SourceError) as excinfo:
        await probe.collect(SITE, TODAY_ONLY)
    assert excinfo.value.reason == "unreachable" and excinfo.value.recoverable


_HUGE = 10**400  # entier JSON valide, mais hors de portée d'un flottant


def test_parse_cwv_rejects_a_huge_integer_percentile_and_score() -> None:
    origin = {"LARGEST_CONTENTFUL_PAINT_MS": {"percentile": _HUGE}}
    for payload in (
        _payload(origin=origin),
        _payload(origin={"CUMULATIVE_LAYOUT_SHIFT_SCORE": {"percentile": -_HUGE}}),
        _payload(origin=_ORIGIN, score=_HUGE),
        _payload(origin=_ORIGIN, score=-_HUGE),
    ):
        with pytest.raises(SourceError) as excinfo:
            parse_cwv(payload, day=TODAY)
        assert excinfo.value.reason == "api_error" and excinfo.value.recoverable


@pytest.mark.parametrize(
    "body",
    [
        '{"lighthouseResult": {}, "originLoadingExperience": {"metrics": '
        '{"LARGEST_CONTENTFUL_PAINT_MS": {"percentile": 1' + "0" * 400 + "}}}}",
        '{"lighthouseResult": {"categories": {"performance": {"score": 1' + "0" * 400 + "}}}}",
    ],
)
async def test_cwv_source_types_a_huge_integer_from_raw_json(body: str) -> None:
    source = CwvSource(
        api_key="cle",
        client=_client(lambda request: httpx.Response(200, content=body.encode())),
        today=lambda: TODAY,
    )
    with pytest.raises(SourceError) as excinfo:
        await source.collect(SITE, TODAY_ONLY)
    assert excinfo.value.reason == "api_error" and excinfo.value.recoverable


async def test_cwv_non_ascii_api_key_is_a_typed_definitive_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("aucun appel attendu")

    source = CwvSource(api_key="clé-secrète", client=_client(handler), today=lambda: TODAY)
    with pytest.raises(SourceError) as excinfo:
        await source.collect(SITE, TODAY_ONLY)
    error = excinfo.value
    assert (error.reason, error.recoverable) == ("api_key_rejected", False)
    assert "secr" not in str(error) and "secr" not in repr(error.__dict__)
    assert error.__cause__ is None


async def test_window_end_equal_to_today_is_included() -> None:
    # Un `day < end` à la place de `day <= end` ferait échouer ces deux tests.
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=_payload(origin=_ORIGIN))

    source = CwvSource(api_key="cle", client=_client(handler), today=lambda: TODAY)
    assert len(await source.collect(SITE, DayRange(date(2026, 9, 20), TODAY))) == 4
    assert len(seen) == 1


async def test_probes_window_end_equal_to_today_is_included() -> None:
    calls: list = []
    probe = _probe(_tls("valid", 45), _page(200), calls)
    assert len(await probe.collect(SITE, DayRange(date(2026, 9, 20), TODAY))) == 2
    assert len(calls) == 1
