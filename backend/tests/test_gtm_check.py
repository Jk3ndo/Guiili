"""analyze_gtm : detection statique de la config GTM. Aucun reseau."""

import httpx

from app.services.gtm_check import GtmCheck, analyze_gtm, check_gtm
from app.services.page_fetch import PageSnapshot

_GTM = "GTM-ABCD123"


def _snap(
    html: str,
    *,
    headers: dict | None = None,
    history: tuple = (),
    redirected: bool = False,
) -> PageSnapshot:
    return PageSnapshot(
        url="https://site.test/",
        final_url="https://site.test/",
        status=200,
        html=html,
        headers={k.lower(): v for k, v in (headers or {}).items()},
        redirected=redirected,
        history=history,
    )


_STANDARD_SNIPPET = f"""<!doctype html><html><head>
<script>(function(w,d,s,l,i){{w[l]=w[l]||[];}})(window,document,'script','dataLayer','{_GTM}');
</script>
<script src="https://www.googletagmanager.com/gtm.js?id={_GTM}"></script>
</head><body>
<noscript><iframe src="https://www.googletagmanager.com/ns.html?id={_GTM}"></iframe></noscript>
</body></html>"""


def test_standard_install_is_clean() -> None:
    check = analyze_gtm(_snap(_STANDARD_SNIPPET))
    assert check.containers == (_GTM,)
    assert check.snippet_form == "standard"
    assert check.snippet_in_head is True
    assert check.data_layer_name == "dataLayer"
    assert check.consent_platform is None
    assert check.gtm_consent_gated is False
    assert check.findings == ()


def test_consent_gated_via_onetrust_text_plain() -> None:
    html = _STANDARD_SNIPPET.replace(
        '<script src="https://www.googletagmanager.com/gtm.js',
        '<script type="text/plain" class="optanon-category-C0002" '
        'src="https://www.googletagmanager.com/gtm.js',
    ).replace(
        "</head>",
        '<script src="https://cdn.cookielaw.org/scripttemplates/otSDKStub.js"></script></head>',
    )
    check = analyze_gtm(_snap(html))
    assert check.consent_platform == "onetrust"
    assert check.gtm_consent_gated is True
    assert any(f.code == "gtm_consent_gated" for f in check.findings)


def test_csp_header_without_gtm_blocks_preview() -> None:
    check = analyze_gtm(
        _snap(
            _STANDARD_SNIPPET,
            headers={
                "Content-Security-Policy": "default-src 'self'; script-src 'self' 'unsafe-inline'"
            },
        )
    )
    assert check.csp_present is True
    assert check.csp_allows_gtm is False
    assert check.csp_blocks_preview is True
    finding = next(f for f in check.findings if f.code == "gtm_preview_csp_block")
    assert finding.severity == "high"


def test_csp_meta_allowing_gtm_is_fine() -> None:
    html = _STANDARD_SNIPPET.replace(
        "</head>",
        '<meta http-equiv="Content-Security-Policy" '
        "content=\"script-src 'self' https://www.googletagmanager.com\"></head>",
    )
    check = analyze_gtm(_snap(html))
    assert check.csp_present is True
    assert check.csp_allows_gtm is True
    assert check.csp_blocks_preview is False
    assert not any(f.code == "gtm_preview_csp_block" for f in check.findings)


def test_custom_datalayer_name_flagged() -> None:
    html = _STANDARD_SNIPPET.replace("'dataLayer'", "'myDL'")
    check = analyze_gtm(_snap(html))
    assert check.data_layer_name == "myDL"
    assert any(f.code == "gtm_custom_datalayer" for f in check.findings)


def test_multiple_containers_flagged() -> None:
    html = (
        _STANDARD_SNIPPET
        + '<script src="https://www.googletagmanager.com/gtm.js?id=GTM-ZZZ9999"></script>'
    )
    check = analyze_gtm(_snap(html))
    assert set(check.containers) == {_GTM, "GTM-ZZZ9999"}
    assert any(f.code == "gtm_multiple_containers" for f in check.findings)


def test_noscript_only_flagged() -> None:
    html = (
        "<html><head></head><body><noscript>"
        f'<iframe src="https://www.googletagmanager.com/ns.html?id={_GTM}"></iframe>'
        "</noscript></body></html>"
    )
    check = analyze_gtm(_snap(html))
    assert check.snippet_form == "noscript_only"
    assert any(f.code == "gtm_noscript_only" for f in check.findings)


def test_server_side_container_flagged() -> None:
    html = _STANDARD_SNIPPET.replace(
        "https://www.googletagmanager.com/gtm.js", "https://sgtm.site.test/gtm.js"
    )
    check = analyze_gtm(_snap(html))
    assert check.server_side is True
    assert any(f.code == "gtm_server_side" for f in check.findings)


def test_ga4_hardcoded_alongside_gtm_flagged() -> None:
    html = _STANDARD_SNIPPET.replace(
        "</head>",
        '<script src="https://www.googletagmanager.com/gtag/js?id=G-ABC1234567"></script></head>',
    )
    check = analyze_gtm(_snap(html))
    assert "G-ABC1234567" in check.ga4_tags
    assert any(f.code == "ga4_hardcoded_alongside_gtm" for f in check.findings)


def test_no_gtm_at_all_is_absent_no_findings() -> None:
    check = analyze_gtm(_snap("<html><head></head><body>rien</body></html>"))
    assert check.snippet_form == "absent"
    assert check.containers == ()
    assert check.findings == ()


def test_redirect_dropping_query_flagged_low() -> None:
    check = analyze_gtm(
        _snap(
            _STANDARD_SNIPPET,
            redirected=True,
            history=((301, "https://site.test/home"),),
        )
    )
    assert check.query_stripped_on_redirect is True
    finding = next(f for f in check.findings if f.code == "gtm_query_stripped")
    assert finding.severity == "low"


def test_analyze_is_pure_dataclass() -> None:
    check = analyze_gtm(_snap(_STANDARD_SNIPPET))
    assert isinstance(check, GtmCheck)
    assert check.checked_at is None  # rempli par check_gtm, pas analyze_gtm
    assert check.error is None


async def test_check_gtm_fetches_and_analyzes(monkeypatch) -> None:
    async def fake_fetch(url, **kw):
        _ = (url, kw)
        return _snap(_STANDARD_SNIPPET, headers={"content-type": "text/html"})

    monkeypatch.setattr("app.services.gtm_check.fetch_page", fake_fetch)
    check = await check_gtm("site.test")
    assert check.containers == (_GTM,)
    assert check.checked_at is not None


async def test_check_gtm_never_raises_on_network_error(monkeypatch) -> None:
    async def boom(url, **kw):
        _ = (url, kw)
        raise httpx.ConnectError("down")

    monkeypatch.setattr("app.services.gtm_check.fetch_page", boom)
    check = await check_gtm("site.test")
    assert check.error == "fetch_error"
    assert check.findings == ()
