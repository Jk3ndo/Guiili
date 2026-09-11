"""Tests de `gtm_headless.py`.

`verify_gtm` lance un vrai navigateur Chromium — jamais exerce ici (voir la
docstring du module). On teste uniquement la logique pure : derivation des
findings depuis un resultat observe, et la serialisation vers un dict JSONB.
"""

from datetime import UTC, datetime

from app.services.gtm_headless import (
    GtmHeadlessResult,
    _derive_findings,
    _is_gtm_csp_violation,
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
