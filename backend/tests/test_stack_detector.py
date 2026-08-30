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
