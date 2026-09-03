"""Detection de stack front-end / back-end par une requete HTTP legere.

`analyze_response(html, headers, cookies)` est pur et couvre tous les cas ;
`detect_stack(url)` enrobe le fetch httpx (mockable via `httpx.MockTransport`).

Quand aucun marqueur connu ne matche, `StackDetection.candidates` porte des
hypotheses (label + raison) que l'UI propose a l'utilisateur pour qu'il
confirme / choisisse / saisisse sa stack.
"""

from __future__ import annotations

import re
import ssl
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

import httpx

from app.models.enums import StackKind

_TIMEOUT = httpx.Timeout(8.0)
_MAX_BYTES = 400_000

_GENERATOR_RE = re.compile(
    r'<meta[^>]+name=["\']generator["\'][^>]+content=["\']([^"\']+)["\']',
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class StackGuess:
    """Hypothese de techno : ce qu'on suppose + l'indice qui le suggere."""

    label: str
    reason: str


@dataclass(frozen=True, slots=True)
class StackDetection:
    stack: StackKind
    signals: tuple[str, ...]
    confidence: float
    # Hypotheses proposees quand `stack` est generic/unknown ou peu sur.
    candidates: tuple[StackGuess, ...] = field(default_factory=tuple)
    # "ssl_verification_failed" | "fetch_error" | "http_4xx" | "non_html" | None
    error: str | None = None


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
    (
        StackKind.VITE,
        [
            ("vite-client", "/@vite/client"),
            ("vite-assets", 'type="module" src="/assets/index-'),
            ("vite-react-refresh", "/@react-refresh"),
        ],
    ),
    (
        StackKind.REACT,
        [
            ("react-root-static", 'id="root"'),
            ("react-dom-marker", "data-reactroot"),
            ("react-devtools", "__react_devtools_global_hook__"),
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
    ("drupal", StackKind.PHP),
    ("joomla", StackKind.PHP),
    ("hugo", StackKind.GENERIC),
    ("gatsby", StackKind.GENERIC),
]

# React nu / Vite : signaux faibles, on tranche apres les frameworks server-side
# et apres Next/Nuxt/Angular/Vue.
_RESOLUTION_ORDER: tuple[StackKind, ...] = (
    StackKind.WOOCOMMERCE,
    StackKind.WORDPRESS,
    StackKind.NEXTJS,
    StackKind.NUXT,
    StackKind.ANGULAR,
    StackKind.VUE,
    StackKind.VITE,
    StackKind.REACT,
)

# Pour REACT/VITE il faut le conteneur de montage ET un bundle : evite de
# confondre avec une page qui contient juste `id="root"` par hasard.
_NEEDS_BUNDLE = {StackKind.REACT}
_BUNDLE_HINTS = ("/static/js/", "/assets/", "react-dom", "/@vite/", 'type="module"')
_SPA_SCRIPT_HINT = 2  # nb mini de <script> pour parler de SPA


def _cookie_names(cookies: Sequence[str] | None) -> list[str]:
    """`["PHPSESSID=abc; path=/", ...]` -> `["phpsessid", ...]`."""
    names: list[str] = []
    for raw in cookies or ():
        head = raw.split("=", 1)[0].strip().lower()
        if head:
            names.append(head)
    return names


def _php_signal(
    lower_headers: Mapping[str, str], cookie_names: Sequence[str], body: str
) -> str | None:
    powered = lower_headers.get("x-powered-by", "")
    if "php" in powered:
        return "hdr-x-powered-php"
    if "phpsessid" in cookie_names:
        return "cookie-phpsessid"
    if "laravel_session" in cookie_names or "xsrf-token" in cookie_names:
        return "cookie-laravel"
    if re.search(r'(?:href|src|action)=["\'][^"\']*\.php(?:[?"\'#/]|$)', body):
        return "links-dot-php"
    return None


def _speculate(
    body: str, lower_headers: Mapping[str, str], cookie_names: Sequence[str]
) -> list[StackGuess]:
    guesses: list[StackGuess] = []

    def add(label: str, reason: str) -> None:
        if not any(g.label == label for g in guesses):
            guesses.append(StackGuess(label=label, reason=reason))

    has_mount_node = 'id="root"' in body or 'id="app"' in body
    if "cdn.tailwindcss.com" in body:
        add("Tailwind CSS (CDN)", "script cdn.tailwindcss.com — build maison ou page statique")
    if has_mount_node and body.count("<script") >= _SPA_SCRIPT_HINT:
        add(
            "SPA JavaScript (React / Vue)",
            "conteneur de montage #root/#app + bundles JS, sans marqueur de framework",
        )
    if "jquery" in body and ("bootstrap" in body or "getbootstrap.com" in body):
        add(
            "Site rendu cote serveur (PHP / Rails / Django)",
            "jQuery + Bootstrap, HTML complet renvoye par le serveur",
        )
    if "phpsessid" in cookie_names:
        add("PHP", "cookie de session PHPSESSID")
    if "laravel_session" in cookie_names or "xsrf-token" in cookie_names:
        add("Laravel", "cookies laravel_session / XSRF-TOKEN")
    if "symfony" in cookie_names:
        add("Symfony", "cookie de session symfony")
    if re.search(r'(?:href|src|action)=["\'][^"\']*\.php', body):
        add("PHP", "liens vers des fichiers .php")
    if re.search(r'(?:href|src|action)=["\'][^"\']*\.aspx?', body) or "asp.net" in body:
        add("ASP.NET", "liens .aspx / mention asp.net")

    server = lower_headers.get("server", "")
    if "cloudflare" in server:
        add("Cloudflare (proxy / CDN)", "en-tete Server: cloudflare")
    if "vercel" in server or "x-vercel-id" in lower_headers:
        add("Vercel (hebergement)", "en-tetes Vercel — souvent Next.js / SvelteKit")
    if "netlify" in server or "x-nf-request-id" in lower_headers:
        add("Netlify (hebergement)", "en-tetes Netlify — site statique / Jamstack")
    if "github.io" in body or server == "github.com":
        add("GitHub Pages", "hebergement GitHub Pages — site statique")

    generator = _GENERATOR_RE.search(body)
    if generator:
        add(generator.group(1).strip(), "balise <meta name=generator>")

    if not guesses and ("<html" in body or "<!doctype html" in body):
        add("HTML rendu cote serveur", "page HTML complete, aucune empreinte technique reconnue")

    return guesses[:6]


def analyze_response(
    html: str,
    headers: Mapping[str, str] | None = None,
    cookies: Sequence[str] | None = None,
) -> StackDetection:
    body = html.lower()
    lower_headers = {k.lower(): v.lower() for k, v in (headers or {}).items()}
    cookie_names = _cookie_names(cookies)

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

    speculation = tuple(_speculate(body, lower_headers, cookie_names))

    # 4. Resolution par priorite.
    for stack in _RESOLUTION_ORDER:
        if stack not in matched:
            continue
        if stack in _NEEDS_BUNDLE and not any(hint in body for hint in _BUNDLE_HINTS):
            continue
        signals = tuple(matched[stack])
        confidence = min(0.95, 0.55 + 0.15 * len(signals))
        return StackDetection(stack, signals, confidence)

    if generator_stack is not None:  # ex. shopify / wix -> generic ; drupal -> php
        return StackDetection(generator_stack, tuple(matched[generator_stack]), 0.9)

    # 5. PHP sans framework precis (cookies / en-tetes / liens .php).
    php = _php_signal(lower_headers, cookie_names, body)
    if php is not None:
        return StackDetection(StackKind.PHP, (php,), 0.7, candidates=speculation)

    # 6. Generique / inconnu — on remonte les hypotheses.
    if "<html" in body or "<!doctype html" in body:
        return StackDetection(StackKind.GENERIC, (), 0.3, candidates=speculation)

    return StackDetection(StackKind.UNKNOWN, (), 0.0, candidates=speculation)


# Domaines de démo (frontend/lib/mock/workspaces.ts) : pas de vrai site à
# sonder, on renvoie une stack figée en mode mock.
DEMO_STACKS: dict[str, StackKind] = {
    "boutique-verte.fr": StackKind.NEXTJS,
    "atelier-nord.com": StackKind.WORDPRESS,
    "studiolumen.io": StackKind.VUE,
    "cap-horizon.co": StackKind.ANGULAR,
}


async def demo_detector(url: str) -> StackDetection:
    host = httpx.URL(url).host
    stack = DEMO_STACKS.get(host, StackKind.UNKNOWN)
    return StackDetection(stack, ("demo",), 1.0 if stack is not StackKind.UNKNOWN else 0.0)


def _is_ssl_error(exc: Exception) -> bool:
    cause: BaseException | None = exc
    while cause is not None:
        if isinstance(cause, ssl.SSLError):
            return True
        text = str(cause).lower()
        if "certificate" in text or "ssl" in text or "tls" in text:
            return True
        cause = cause.__cause__
    return False


async def detect_stack(
    url: str,
    *,
    client: httpx.AsyncClient | None = None,
    allow_insecure: bool = False,
) -> StackDetection:
    owns_client = client is None
    http = client or httpx.AsyncClient(
        timeout=_TIMEOUT,
        follow_redirects=True,
        headers={"User-Agent": "ControlCenterBot/1.0"},
        verify=not allow_insecure,
    )
    try:
        response = await http.get(url)
    except httpx.HTTPError as exc:
        if not allow_insecure and _is_ssl_error(exc):
            return StackDetection(
                StackKind.UNKNOWN,
                ("ssl-verify-failed",),
                0.0,
                error="ssl_verification_failed",
            )
        return StackDetection(StackKind.UNKNOWN, ("fetch-error",), 0.0, error="fetch_error")
    finally:
        if owns_client:
            await http.aclose()

    if response.status_code >= 400:
        return StackDetection(
            StackKind.UNKNOWN, (f"http-{response.status_code}",), 0.0, error="http_error"
        )

    body = response.text[:_MAX_BYTES]
    content_type = response.headers.get("content-type", "").lower()
    if "html" not in content_type and "<html" not in body.lower():
        return StackDetection(StackKind.UNKNOWN, ("non-html",), 0.0, error="non_html")

    return analyze_response(body, dict(response.headers), response.headers.get_list("set-cookie"))
