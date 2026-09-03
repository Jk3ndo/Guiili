"""Detection de stack : `analyze_response` (pur) + `detect_stack` (httpx mock)."""

import httpx
import pytest

from app.models.enums import StackKind
from app.services.stack_detector import analyze_response, detect_stack

_NEXT_HTML = """<!doctype html><html><head><title>x</title></head>
<body><div id="__next"></div>
<script src="/_next/static/chunks/main.js"></script>
<script id="__NEXT_DATA__" type="application/json">{"props":{}}</script>
</body></html>"""

_WP_HTML = """<!doctype html><html><head>
<meta name="generator" content="WordPress 6.5.2" />
<link rel="stylesheet" href="/wp-content/themes/x/style.css" />
</head><body>hello</body></html>"""

_WOO_HTML = """<!doctype html><html><head>
<link href="/wp-content/plugins/woocommerce/assets/css/woocommerce.css" rel="stylesheet">
</head><body class="woocommerce-page"><form>wc-ajax=add_to_cart</form></body></html>"""

_NUXT_HTML = """<!doctype html><html><body><div id="__nuxt"></div>
<script>window.__NUXT__=(function(){return {}})()</script>
<link rel="preload" href="/_nuxt/entry.js" as="script"></body></html>"""

_VUE_HTML = """<!doctype html><html><body>
<div id="app" data-server-rendered="true"><span data-v-7ba5bd90>hi</span></div>
</body></html>"""

_NG_HTML = """<!doctype html><html><body>
<app-root ng-version="17.3.1"></app-root></body></html>"""

_PLAIN_HTML = "<!doctype html><html><head><title>Plain</title></head><body>hi</body></html>"


@pytest.mark.parametrize(
    ("html", "expected"),
    [
        (_NEXT_HTML, StackKind.NEXTJS),
        (_WP_HTML, StackKind.WORDPRESS),
        (_WOO_HTML, StackKind.WOOCOMMERCE),
        (_NUXT_HTML, StackKind.NUXT),
        (_VUE_HTML, StackKind.VUE),
        (_NG_HTML, StackKind.ANGULAR),
        (_PLAIN_HTML, StackKind.GENERIC),
        ("garbage not even html", StackKind.UNKNOWN),
    ],
)
def test_analyze_response_classifies_each_stack(html: str, expected: StackKind) -> None:
    assert analyze_response(html).stack is expected


def test_woocommerce_wins_over_wordpress() -> None:
    mixed = _WP_HTML.replace(
        "</head>",
        '<link href="/wp-content/plugins/woocommerce/x.css"></head>',
    )
    assert analyze_response(mixed).stack is StackKind.WOOCOMMERCE


def test_header_signal_beats_body() -> None:
    detection = analyze_response(_PLAIN_HTML, headers={"X-Powered-By": "Next.js"})
    assert detection.stack is StackKind.NEXTJS
    assert detection.confidence >= 0.8


def test_generator_meta_detection() -> None:
    detection = analyze_response(_WP_HTML)
    assert detection.stack is StackKind.WORDPRESS
    assert "generator:wordpress" in detection.signals


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_detect_stack_fetches_and_analyzes() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "https://shop.example/"
        return httpx.Response(
            200, text=_WOO_HTML, headers={"content-type": "text/html; charset=utf-8"}
        )

    async with _client(handler) as client:
        result = await detect_stack("https://shop.example/", client=client)
    assert result.stack is StackKind.WOOCOMMERCE


async def test_detect_stack_handles_http_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    async with _client(handler) as client:
        result = await detect_stack("https://down.example/", client=client)
    assert result.stack is StackKind.UNKNOWN


async def test_detect_stack_handles_transport_failure() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route")

    async with _client(handler) as client:
        result = await detect_stack("https://nope.example/", client=client)
    assert result.stack is StackKind.UNKNOWN
    assert result.error == "fetch_error"


# --------------------------------------------------------------------------- #
#  P4 : React / Vite / PHP + hypotheses + erreurs SSL                          #
# --------------------------------------------------------------------------- #

_CRA_HTML = """<!doctype html><html><head><title>App</title></head>
<body><div id="root"></div>
<script src="/static/js/main.4f2a1b.chunk.js"></script>
<script src="/static/js/2.abc.chunk.js"></script></body></html>"""

_VITE_HTML = """<!doctype html><html><head>
<script type="module" src="/assets/index-Bx3k9.js"></script>
<link rel="stylesheet" href="/assets/index-9aa.css"></head>
<body><div id="app"></div></body></html>"""

_PHP_LOGIN_HTML = """<!doctype html><html lang="en"><head><title>Se connecter</title>
<link rel="stylesheet" href="assets/bootstrap/bootstrap.min.css"></head>
<body><form action="index.php" method="post"><input name="user"></form>
<script src="assets/jquery.min.js"></script></body></html>"""

_LANDING_HTML = """<!doctype html><html lang="fr"><head><title>QR Nyama</title>
<script src="https://cdn.tailwindcss.com"></script></head>
<body><nav>menu</nav><a href="https://app.qrnyama.com/signin">Se connecter</a>
<script>document.querySelector('nav')</script></body></html>"""


def test_react_bare_detected_with_bundle() -> None:
    detection = analyze_response(_CRA_HTML)
    assert detection.stack is StackKind.REACT
    assert "react-root-static" in detection.signals


def test_react_root_without_bundle_stays_generic() -> None:
    thin = '<!doctype html><html><body><div id="root"></div></body></html>'
    assert analyze_response(thin).stack is StackKind.GENERIC


def test_vite_module_assets_detected() -> None:
    assert analyze_response(_VITE_HTML).stack is StackKind.VITE


def test_php_from_session_cookie() -> None:
    detection = analyze_response(_PLAIN_HTML, cookies=["PHPSESSID=abc123; path=/; HttpOnly"])
    assert detection.stack is StackKind.PHP
    assert detection.signals == ("cookie-phpsessid",)


def test_php_from_x_powered_by_header() -> None:
    assert analyze_response(_PLAIN_HTML, headers={"X-Powered-By": "PHP/8.2"}).stack is StackKind.PHP


def test_php_login_page_gives_php_and_candidates() -> None:
    detection = analyze_response(_PHP_LOGIN_HTML, cookies=["PHPSESSID=x"])
    assert detection.stack is StackKind.PHP
    labels = {g.label for g in detection.candidates}
    assert "PHP" in labels


def test_static_landing_page_candidates() -> None:
    detection = analyze_response(_LANDING_HTML)
    assert detection.stack is StackKind.GENERIC
    labels = {g.label for g in detection.candidates}
    assert "Tailwind CSS (CDN)" in labels
    # chaque hypothese porte une raison lisible
    assert all(g.reason for g in detection.candidates)


async def test_detect_stack_flags_ssl_error_when_verifying() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("[SSL: CERTIFICATE_VERIFY_FAILED] certificate has expired")

    async with _client(handler) as client:
        result = await detect_stack("https://expired.example/", client=client)
    assert result.stack is StackKind.UNKNOWN
    assert result.error == "ssl_verification_failed"
    assert result.signals == ("ssl-verify-failed",)


async def test_detect_stack_allow_insecure_treats_ssl_error_as_fetch_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("[SSL: CERTIFICATE_VERIFY_FAILED] certificate has expired")

    async with _client(handler) as client:
        result = await detect_stack("https://expired.example/", client=client, allow_insecure=True)
    assert result.error == "fetch_error"
