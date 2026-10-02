"""Tests de `gtm_headless.py`.

`verify_gtm` lance un vrai navigateur Chromium — jamais exerce ici (voir la
docstring du module). On teste la logique pure : derivation des findings depuis
un resultat observe, la serialisation vers un dict JSONB, et (avec un faux
Playwright) les arguments de lancement du navigateur.
"""

import asyncio
from datetime import UTC, datetime

from app.services import gtm_headless
from app.services.gtm_headless import (
    _MAX_GA4_IDS,
    GtmHeadlessResult,
    _derive_findings,
    _ga4_id_from_url,
    _is_ads_request,
    _is_ga4_collect,
    _is_gtm_csp_violation,
    _record_ga4_id,
    headless_result_to_dict,
)


def test_derive_findings_gtm_not_loaded() -> None:
    findings = _derive_findings(
        gtm_js_loaded=False,
        containers_initialised=(),
        datalayer_present=False,
        csp_console_errors=(),
    )
    codes = [f.code for f in findings]
    assert "headless_gtm_not_loaded" in codes
    assert findings[0].severity == "high"


def test_derive_findings_loaded_but_no_container() -> None:
    findings = _derive_findings(
        gtm_js_loaded=True,
        containers_initialised=(),
        datalayer_present=True,
        csp_console_errors=(),
    )
    codes = [f.code for f in findings]
    assert "headless_container_not_initialised" in codes
    assert "headless_gtm_not_loaded" not in codes


def test_derive_findings_datalayer_missing() -> None:
    findings = _derive_findings(
        gtm_js_loaded=True,
        containers_initialised=("GTM-ABCD",),
        datalayer_present=False,
        csp_console_errors=(),
    )
    codes = [f.code for f in findings]
    assert "headless_datalayer_missing" in codes


def test_derive_findings_csp_blocks_gtm() -> None:
    findings = _derive_findings(
        gtm_js_loaded=False,
        containers_initialised=(),
        datalayer_present=False,
        csp_console_errors=("Refused to load ... Content Security Policy directive",),
    )
    codes = [f.code for f in findings]
    assert "headless_csp_blocks_gtm" in codes
    assert "headless_gtm_not_loaded" in codes  # les 2 co-existent


def test_is_gtm_csp_violation_true_when_gtm_itself_blocked() -> None:
    message = (
        "Refused to load the script 'https://www.googletagmanager.com/gtm.js?id=GTM-X' "
        'because it violates the following Content Security Policy directive: '
        '"script-src \'self\'".'
    )
    assert _is_gtm_csp_violation(message) is True


def test_is_gtm_csp_violation_false_when_other_resource_blocked_even_if_gtm_mentioned() -> None:
    # Cas reel observe sur qaopscareer.com : le beacon Cloudflare est bloque,
    # googletagmanager.com apparait seulement dans la liste des sources
    # *autorisees* de la directive citee par Chrome — pas la ressource bloquee.
    message = (
        "Loading the script 'https://static.cloudflareinsights.com/beacon.min.js' "
        "violates the following Content Security Policy directive: "
        "\"script-src 'self' 'unsafe-inline' https://www.googletagmanager.com "
        'https://www.google-analytics.com". The action has been blocked.'
    )
    assert _is_gtm_csp_violation(message) is False


def test_is_gtm_csp_violation_false_without_csp_hint() -> None:
    assert _is_gtm_csp_violation("Uncaught TypeError: x is not a function") is False


def test_derive_findings_all_healthy_returns_empty() -> None:
    findings = _derive_findings(
        gtm_js_loaded=True,
        containers_initialised=("GTM-ABCD",),
        datalayer_present=True,
        csp_console_errors=(),
    )
    assert findings == ()


def test_headless_result_to_dict_roundtrip() -> None:
    result = GtmHeadlessResult(
        gtm_js_loaded=True,
        containers_initialised=("GTM-ABCD",),
        datalayer_present=True,
        gtm_events=("gtm.js", "gtm.load"),
        requests_before_consent=True,
        csp_console_errors=(),
        findings=(),
        checked_at=datetime(2026, 9, 11, 12, 0, tzinfo=UTC),
    )
    out = headless_result_to_dict(result)
    assert out["gtm_js_loaded"] is True
    assert out["containers_initialised"] == ["GTM-ABCD"]
    assert out["gtm_events"] == ["gtm.js", "gtm.load"]
    assert out["checked_at"] == "2026-09-11T12:00:00+00:00"
    assert out["error"] is None
    assert out["findings"] == []


def test_headless_result_to_dict_serializes_findings() -> None:
    result = GtmHeadlessResult(
        gtm_js_loaded=False,
        containers_initialised=(),
        datalayer_present=False,
        gtm_events=(),
        requests_before_consent=False,
        csp_console_errors=(),
        findings=_derive_findings(
            gtm_js_loaded=False,
            containers_initialised=(),
            datalayer_present=False,
            csp_console_errors=(),
        ),
        checked_at=datetime(2026, 9, 11, 12, 0, tzinfo=UTC),
    )
    out = headless_result_to_dict(result)
    assert out["findings"][0]["code"] == "headless_gtm_not_loaded"
    assert out["findings"][0]["severity"] == "high"


def test_ga4_collect_detection_and_measurement_id() -> None:
    url = "https://www.google-analytics.com/g/collect?v=2&tid=G-ABC123XYZ&en=page_view"
    assert _is_ga4_collect(url)
    assert _ga4_id_from_url(url) == "G-ABC123XYZ"
    regional = "https://region1.analytics.google.com/g/collect?v=2&tid=G-ZZZ999"
    assert _is_ga4_collect(regional)
    assert _ga4_id_from_url(regional) == "G-ZZZ999"


def test_non_collect_requests_are_ignored() -> None:
    assert not _is_ga4_collect("https://www.googletagmanager.com/gtm.js?id=GTM-AAAA111")
    assert not _is_ga4_collect("https://www.google-analytics.com/analytics.js")
    assert _ga4_id_from_url("https://example.com/x") is None


def test_ads_request_detection() -> None:
    assert _is_ads_request(
        "https://www.googleadservices.com/pagead/conversion/123456789/?label=x"
    )
    assert _is_ads_request(
        "https://googleads.g.doubleclick.net/pagead/viewthroughconversion/123456789/"
    )
    assert not _is_ads_request("https://www.googletagmanager.com/gtag/js?id=G-1")


def test_ads_request_ignores_youtube_embed_and_generic_ad_calls() -> None:
    # Un embed YouTube appelle googleads.g.doubleclick.net/pagead/id : ce n'est pas
    # une conversion Google Ads du site.
    assert not _is_ads_request("https://googleads.g.doubleclick.net/pagead/id")
    assert not _is_ads_request("https://googleads.g.doubleclick.net/pagead/ads?client=x")
    assert not _is_ads_request("https://www.googleadservices.com/pagead/conversion/1/")
    assert not _is_ads_request("https://example.com/pagead/conversion/123456789/")


def test_headless_result_dict_exposes_new_fields_with_defaults() -> None:
    result = GtmHeadlessResult(
        gtm_js_loaded=True,
        containers_initialised=("GTM-ABCD",),
        datalayer_present=True,
        gtm_events=(),
        requests_before_consent=True,
        csp_console_errors=(),
        findings=(),
        checked_at=datetime(2026, 9, 24, 12, 0, tzinfo=UTC),
    )
    out = headless_result_to_dict(result)
    assert out["ga4_measurement_ids"] == []
    assert out["ads_requests"] == 0
    assert out["consent_default_seen"] is False

    full = GtmHeadlessResult(
        gtm_js_loaded=True,
        containers_initialised=("GTM-ABCD",),
        datalayer_present=True,
        gtm_events=("page_view",),
        requests_before_consent=True,
        csp_console_errors=(),
        findings=(),
        checked_at=datetime(2026, 9, 24, 12, 0, tzinfo=UTC),
        ga4_measurement_ids=("G-ABC123XYZ",),
        ads_requests=2,
        consent_default_seen=True,
    )
    out = headless_result_to_dict(full)
    assert out["ga4_measurement_ids"] == ["G-ABC123XYZ"]
    assert out["ads_requests"] == 2
    assert out["consent_default_seen"] is True


def test_verify_gtm_launches_chromium_with_the_sandbox_choice_explicit(monkeypatch) -> None:
    # Faux Playwright : aucun vrai navigateur. On capture les arguments de `launch`.
    launch_kwargs: dict[str, object] = {}

    class _FakePage:
        def on(self, *_args: object) -> None:
            return None

        async def goto(self, *_args: object, **_kwargs: object) -> None:
            return None

        async def evaluate(self, *_args: object) -> list[object]:
            return []

    class _FakeBrowser:
        async def new_page(self) -> _FakePage:
            return _FakePage()

        async def close(self) -> None:
            return None

    class _FakeChromium:
        async def launch(self, *args: object, **kwargs: object) -> _FakeBrowser:
            launch_kwargs.update(kwargs)
            return _FakeBrowser()

    class _FakePlaywright:
        chromium = _FakeChromium()

    class _FakeContext:
        async def __aenter__(self) -> _FakePlaywright:
            return _FakePlaywright()

        async def __aexit__(self, *_exc: object) -> None:
            return None

    monkeypatch.setattr(gtm_headless, "async_playwright", _FakeContext)

    result = asyncio.run(gtm_headless.verify_gtm("https://example.com"))

    assert result.error is None
    # Choix explicite (voir le commentaire dans verify_gtm) : jamais laisse au defaut.
    assert launch_kwargs.get("chromium_sandbox") is False


def test_invalid_ga4_tid_is_ignored() -> None:
    base = "https://www.google-analytics.com/g/collect?v=2&tid="
    assert _ga4_id_from_url(base + "G-ABC123XYZ") == "G-ABC123XYZ"
    for bad in ("UA-1234-1", "g-abc123", "G-AB", "G-" + "A" * 21, "<script>", "G-ABC%20123"):
        assert _ga4_id_from_url(base + bad) is None
    ids: list[str] = []
    _record_ga4_id(ids, base + "not-an-id")
    assert ids == []


def test_ga4_ids_are_deduplicated_and_capped() -> None:
    base = "https://www.google-analytics.com/g/collect?v=2&tid="
    ids: list[str] = []
    _record_ga4_id(ids, base + "G-AAAA1")
    _record_ga4_id(ids, base + "G-AAAA1")
    assert ids == ["G-AAAA1"]
    for i in range(_MAX_GA4_IDS + 5):
        _record_ga4_id(ids, f"{base}G-BBBB{i}")
    assert len(ids) == _MAX_GA4_IDS
    assert ids[0] == "G-AAAA1"
