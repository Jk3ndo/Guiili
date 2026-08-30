"""Detection de stack front-end par une requete HTTP legere (pas de headless).

`analyze_response(html, headers)` est pur et couvre tous les cas ; `detect_stack(url)`
enrobe le fetch httpx (mockable via `httpx.MockTransport` dans les tests).
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass

import httpx

from app.models.enums import StackKind

_TIMEOUT = httpx.Timeout(8.0)
_MAX_BYTES = 400_000

_GENERATOR_RE = re.compile(
    r'<meta[^>]+name=["\']generator["\'][^>]+content=["\']([^"\']+)["\']',
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class StackDetection:
    stack: StackKind
    signals: tuple[str, ...]
    confidence: float


# (StackKind, [(nom_signal, motif substring lowercase), ...]) — ordre = priorite.
_HTML_MARKERS: list[tuple[StackKind, list[tuple[str, str]]]] = [
    (
        StackKind.WOOCOMMERCE,
        [
            ("woocommerce-class", "woocommerce-page"),
            ("wc-ajax", "wc-ajax="),
            ("wc-plugin", "/wp-content/plugins/woocommerce/"),
            ("wc-blocks", "wc-blocks"),
        ],
    ),
    (
        StackKind.WORDPRESS,
        [
            ("wp-content", "/wp-content/"),
            ("wp-includes", "/wp-includes/"),
            ("wp-json", "/wp-json/"),
            ("wp-emoji", "wp-emoji-release"),
        ],
    ),
    (
        StackKind.NEXTJS,
        [
            ("next-data", 'id="__next_data__"'),
            ("next-static", "/_next/static/"),
            ("next-image", "/_next/image?"),
        ],
    ),
    (
        StackKind.NUXT,
        [
            ("nuxt-state", "window.__nuxt__"),
            ("nuxt-id", 'id="__nuxt__"'),
            ("nuxt-assets", "/_nuxt/"),
        ],
    ),
    (
        StackKind.ANGULAR,
        [
            ("ng-version", "ng-version="),
            ("app-root", "<app-root"),
            ("ng-hydration", "ngh="),
        ],
    ),
    (
        StackKind.VUE,
        [
            ("vue-ssr", "data-server-rendered"),
            ("vue-scoped", "data-v-"),
            ("vue-global", "window.vue"),
        ],
    ),
]

_HEADER_MARKERS: list[tuple[StackKind, list[tuple[str, str, str]]]] = [
    (StackKind.WORDPRESS, [("hdr-x-powered-wp", "x-powered-by", "wordpress")]),
    (StackKind.WORDPRESS, [("hdr-link-wp-json", "link", "wp-json")]),
    (StackKind.NEXTJS, [("hdr-x-powered-next", "x-powered-by", "next.js")]),
    (StackKind.NEXTJS, [("hdr-x-nextjs", "x-nextjs-cache", "")]),
]

_GENERATOR_MAP: list[tuple[str, StackKind]] = [
    ("woocommerce", StackKind.WOOCOMMERCE),
    ("wordpress", StackKind.WORDPRESS),
    ("wix", StackKind.GENERIC),
    ("shopify", StackKind.GENERIC),
    ("drupal", StackKind.GENERIC),
    ("hugo", StackKind.GENERIC),
    ("gatsby", StackKind.GENERIC),
]


# Ordre de priorite quand plusieurs stacks matchent (le plus specifique gagne).
_RESOLUTION_ORDER: tuple[StackKind, ...] = (
    StackKind.WOOCOMMERCE,
    StackKind.WORDPRESS,
    StackKind.NEXTJS,
    StackKind.NUXT,
    StackKind.ANGULAR,
    StackKind.VUE,
)


def analyze_response(html: str, headers: Mapping[str, str] | None = None) -> StackDetection:
    body = html.lower()
    lower_headers = {k.lower(): v.lower() for k, v in (headers or {}).items()}

    # 1. En-tetes HTTP — signal fort, on tranche tout de suite.
    for stack, checks in _HEADER_MARKERS:
        for name, header, needle in checks:
            value = lower_headers.get(header, "")
            if value and (not needle or needle in value):
                return StackDetection(stack, (name,), 0.9)

    # 2. Collecte de tous les marqueurs HTML.
    matched: dict[StackKind, list[str]] = {}
    for stack, markers in _HTML_MARKERS:
        names = [name for name, needle in markers if needle in body]
        if names:
            matched[stack] = names

    # 3. Balise <meta generator>.
    generator_stack: StackKind | None = None
    generator = _GENERATOR_RE.search(html)
    if generator:
        gen = generator.group(1).lower()
        for needle, stack in _GENERATOR_MAP:
            if needle in gen:
                generator_stack = stack
                matched.setdefault(stack, []).append(f"generator:{needle}")
                break

    # 4. Resolution par priorite.
    for stack in _RESOLUTION_ORDER:
        if stack in matched:
            signals = tuple(matched[stack])
            confidence = min(0.95, 0.55 + 0.15 * len(signals))
            return StackDetection(stack, signals, confidence)

    if generator_stack is not None:  # ex. shopify / wix -> generic
        return StackDetection(generator_stack, tuple(matched[generator_stack]), 0.9)

    if "<html" in body or "<!doctype html" in body:
        return StackDetection(StackKind.GENERIC, (), 0.3)

    return StackDetection(StackKind.UNKNOWN, (), 0.0)


async def detect_stack(url: str, *, client: httpx.AsyncClient | None = None) -> StackDetection:
    owns_client = client is None
    http = client or httpx.AsyncClient(
        timeout=_TIMEOUT, follow_redirects=True, headers={"User-Agent": "ControlCenterBot/1.0"}
    )
    try:
        response = await http.get(url)
    except httpx.HTTPError:
        return StackDetection(StackKind.UNKNOWN, ("fetch-error",), 0.0)
    finally:
        if owns_client:
            await http.aclose()

    if response.status_code >= 400:
        return StackDetection(StackKind.UNKNOWN, (f"http-{response.status_code}",), 0.0)

    body = response.text[:_MAX_BYTES]
    content_type = response.headers.get("content-type", "").lower()
    if "html" not in content_type and "<html" not in body.lower():
        return StackDetection(StackKind.UNKNOWN, ("non-html",), 0.0)

    return analyze_response(body, dict(response.headers))
