"""Analyse statique de la configuration Google Tag Manager d'une page.

`analyze_gtm(page)` est pur. `check_gtm(domain)` enrobe le fetch et ne leve
jamais (renvoie `GtmCheck(error=...)` en cas d'echec reseau).

Cible : reperer et expliquer la classe de probleme « GTM installe mais le mode
previsualisation ne s'y connecte pas » (CSP qui bloque googletagmanager.com,
bannieres de consentement qui gelent GTM, snippet mal place, dataLayer renomme,
conteneurs multiples...).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Literal

import httpx

from app.services.page_fetch import PageSnapshot, fetch_page

Severity = Literal["low", "medium", "high"]

_CONTAINER_RE = re.compile(r"GTM-[A-Z0-9]{4,}")
_GA4_RE = re.compile(r"G-[A-Z0-9]{6,}")
_DL_SNIPPET_RE = re.compile(
    r"\(\s*window\s*,\s*document\s*,\s*['\"]script['\"]\s*,\s*['\"]([^'\"]+)['\"]\s*,\s*['\"]GTM-"
)
_DL_URL_RE = re.compile(r"gtm\.js\?[^\"']*[&?]l=([A-Za-z0-9_]+)")
_GTM_JS_SRC_RE = re.compile(r"src=[\"']https?://([^/\"']+)/gtm\.js")
_GTM_SCRIPT_TAG_RE = re.compile(r"<script\b[^>]*gtm\.js[^>]*>", re.IGNORECASE)
_INLINE_GATED_RE = re.compile(
    r"<script\b[^>]*type=[\"']text/plain[\"'][^>]*>(.*?)</script>",
    re.IGNORECASE | re.DOTALL,
)
_META_TAG_RE = re.compile(r"<meta\b[^>]*>", re.IGNORECASE)

_CONSENT_GATE_HINTS = (
    'type="text/plain"',
    "type='text/plain'",
    "data-cookieconsent",
    "data-cookiecategory",
    "data-category",
    "optanon-category",
)

_CMP_SIGNATURES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("onetrust", ("otsdkstub", "optanon", "onetrust", "cookielaw.org")),
    ("cookiebot", ("cookiebot", "data-cbid", "consent.cookiebot")),
    ("axeptio", ("axeptio",)),
    ("didomi", ("didomi",)),
    ("tarteaucitron", ("tarteaucitron",)),
    ("complianz", ("cmplz", "complianz")),
    ("cookieyes", ("cookieyes",)),
    ("osano", ("osano",)),
    ("klaro", ("klaro",)),
)

_SEV_ORDER: dict[Severity, int] = {"high": 0, "medium": 1, "low": 2}


@dataclass(frozen=True, slots=True)
class GtmFinding:
    code: str
    severity: Severity
    title: str
    detail: str


@dataclass(frozen=True, slots=True)
class GtmCheck:
    containers: tuple[str, ...] = ()
    ga4_tags: tuple[str, ...] = ()
    snippet_in_head: bool | None = None
    snippet_form: Literal["standard", "custom_loader", "noscript_only", "absent"] = "absent"
    data_layer_name: str = "dataLayer"
    consent_platform: str | None = None
    gtm_consent_gated: bool = False
    csp_present: bool = False
    csp_allows_gtm: bool | None = None
    csp_blocks_preview: bool | None = None
    server_side: bool = False
    query_stripped_on_redirect: bool = False
    findings: tuple[GtmFinding, ...] = ()
    checked_at: datetime | None = None
    error: str | None = None


def _csp_value(page: PageSnapshot) -> str | None:
    header = page.headers.get("content-security-policy")
    if header:
        return header.lower()
    for match in _META_TAG_RE.finditer(page.html):
        tag = match.group(0)
        if "content-security-policy" not in tag.lower():
            continue
        # La valeur CSP contient des apostrophes ('self') -> delimiteur double.
        content = re.search(r'content="([^"]*)"', tag) or re.search(
            r"content='([^']*)'", tag
        )
        return content.group(1).lower() if content else ""
    return None


def _consent_gated(html: str) -> bool:
    for match in _GTM_SCRIPT_TAG_RE.finditer(html):
        if any(hint in match.group(0).lower() for hint in _CONSENT_GATE_HINTS):
            return True
    for match in _INLINE_GATED_RE.finditer(html):
        body = match.group(1).lower()
        if "gtm-" in body or "gtm.start" in body:
            return True
    return False


def _data_layer_name(html: str) -> str:
    snippet = _DL_SNIPPET_RE.search(html)
    if snippet:
        return snippet.group(1)
    url = _DL_URL_RE.search(html)
    if url:
        return url.group(1)
    return "dataLayer"


def analyze_gtm(page: PageSnapshot) -> GtmCheck:
    html = page.html
    low = html.lower()

    containers = tuple(dict.fromkeys(_CONTAINER_RE.findall(html)))
    src_match = _GTM_JS_SRC_RE.search(html)
    has_gtm_js = "googletagmanager.com/gtm.js" in low or src_match is not None
    has_ns = "googletagmanager.com/ns.html" in low
    has_inline_snippet = _DL_SNIPPET_RE.search(html) is not None

    if not containers and not has_ns:
        return GtmCheck(snippet_form="absent")

    if has_gtm_js or has_inline_snippet:
        snippet_form: Literal["standard", "custom_loader", "noscript_only", "absent"] = "standard"
    elif has_ns:
        snippet_form = "noscript_only"
    elif containers:
        snippet_form = "custom_loader"
    else:
        snippet_form = "absent"

    head_end = low.find("</head>")
    marker = low.find("gtm.js")
    if marker == -1 and containers:
        marker = low.find(containers[0].lower())
    snippet_in_head: bool | None
    if snippet_form == "absent":
        snippet_in_head = None
    elif marker == -1 or head_end == -1:
        snippet_in_head = None if marker == -1 else True
    else:
        snippet_in_head = marker < head_end

    data_layer_name = _data_layer_name(html)
    gtm_consent_gated = _consent_gated(html)

    consent_platform: str | None = None
    for name, needles in _CMP_SIGNATURES:
        if any(needle in low for needle in needles):
            consent_platform = name
            break

    csp = _csp_value(page)
    csp_present = csp is not None
    csp_allows_gtm = ("googletagmanager.com" in csp) if csp is not None else None
    csp_blocks_preview = (not csp_allows_gtm) if csp is not None else None

    server_side = src_match is not None and src_match.group(1) != "www.googletagmanager.com"

    ga4_tags: tuple[str, ...] = ()
    if "googletagmanager.com/gtag/js" in low:
        ga4_tags = tuple(dict.fromkeys(_GA4_RE.findall(html)))

    query_stripped = page.redirected and any(
        "?" not in location for _, location in page.history
    )

    findings = _build_findings(
        containers=containers,
        snippet_form=snippet_form,
        snippet_in_head=snippet_in_head,
        data_layer_name=data_layer_name,
        gtm_consent_gated=gtm_consent_gated,
        consent_platform=consent_platform,
        csp_blocks_preview=csp_blocks_preview,
        server_side=server_side,
        ga4_tags=ga4_tags,
        query_stripped=query_stripped,
    )

    return GtmCheck(
        containers=containers,
        ga4_tags=ga4_tags,
        snippet_in_head=snippet_in_head,
        snippet_form=snippet_form,
        data_layer_name=data_layer_name,
        consent_platform=consent_platform,
        gtm_consent_gated=gtm_consent_gated,
        csp_present=csp_present,
        csp_allows_gtm=csp_allows_gtm,
        csp_blocks_preview=csp_blocks_preview,
        server_side=server_side,
        query_stripped_on_redirect=query_stripped,
        findings=findings,
    )


def _build_findings(
    *,
    containers: tuple[str, ...],
    snippet_form: str,
    snippet_in_head: bool | None,
    data_layer_name: str,
    gtm_consent_gated: bool,
    consent_platform: str | None,
    csp_blocks_preview: bool | None,
    server_side: bool,
    ga4_tags: tuple[str, ...],
    query_stripped: bool,
) -> tuple[GtmFinding, ...]:
    out: list[GtmFinding] = []

    if csp_blocks_preview:
        out.append(
            GtmFinding(
                "gtm_preview_csp_block",
                "high",
                "La politique de securite de contenu bloque la previsualisation GTM",
                "La CSP de la page ne liste pas googletagmanager.com : le mode "
                "previsualisation de Tag Manager (et Tag Assistant) ne peut pas se "
                "connecter. Ajouter *.googletagmanager.com et tagassistant.google.com "
                "aux directives script-src, connect-src et frame-src.",
            )
        )

    if gtm_consent_gated:
        cmp_label = f" ({consent_platform})" if consent_platform else ""
        out.append(
            GtmFinding(
                "gtm_consent_gated",
                "medium",
                "GTM est gele tant que le visiteur n'a pas accepte les cookies",
                f"Le script GTM est charge en type=\"text/plain\"{cmp_label} : il ne "
                "s'execute qu'apres accord de consentement. Tant que la banniere n'est "
                "pas acceptee, la previsualisation reste vide. Verifier la categorie de "
                "consentement affectee au tag GTM.",
            )
        )

    if data_layer_name != "dataLayer":
        out.append(
            GtmFinding(
                "gtm_custom_datalayer",
                "medium",
                f"Le data layer est renomme en « {data_layer_name} »",
                "Le mode previsualisation et de nombreux modeles de tags supposent un "
                "objet nomme `dataLayer`. Un nom personnalise casse les integrations qui "
                "poussent vers `dataLayer` sans le savoir.",
            )
        )

    if len(containers) >= 2:
        out.append(
            GtmFinding(
                "gtm_multiple_containers",
                "medium",
                f"{len(containers)} conteneurs GTM sur la page ({', '.join(containers)})",
                "Plusieurs conteneurs se chargent simultanement : la previsualisation "
                "peut s'attacher au mauvais, et les tags risquent de se declencher en "
                "double. Consolider sur un seul conteneur.",
            )
        )

    if snippet_form == "noscript_only":
        out.append(
            GtmFinding(
                "gtm_noscript_only",
                "medium",
                "Seule la balise <noscript> de GTM est presente",
                "Le fragment JavaScript principal de GTM est absent : seul l'iframe "
                "de repli <noscript> a ete pose. GTM ne se charge pas pour les visiteurs "
                "avec JavaScript actif. Reinserer le snippet complet dans <head>.",
            )
        )

    if snippet_form in ("standard", "custom_loader") and snippet_in_head is False:
        out.append(
            GtmFinding(
                "gtm_snippet_not_in_head",
                "low",
                "Le snippet GTM n'est pas dans <head>",
                "Le snippet est charge plus bas dans la page : les evenements et tags "
                "declenches avant son chargement sont perdus. Le placer le plus haut "
                "possible dans <head>.",
            )
        )

    if server_side:
        out.append(
            GtmFinding(
                "gtm_server_side",
                "low",
                "Conteneur servi en first-party (server-side GTM)",
                "gtm.js est servi depuis un domaine personnalise. La previsualisation "
                "d'un conteneur web servi en first-party demande une configuration "
                "specifique (transport_url) — a verifier si le preview echoue.",
            )
        )

    if ga4_tags:
        out.append(
            GtmFinding(
                "ga4_hardcoded_alongside_gtm",
                "low",
                f"GA4 est cable en dur sur la page en plus de GTM ({', '.join(ga4_tags)})",
                "Un tag gtag.js GA4 est present dans le code de la page alors qu'un "
                "conteneur GTM existe. Risque de double comptage si GA4 est aussi "
                "declenche depuis GTM. Choisir une seule source.",
            )
        )

    if query_stripped:
        out.append(
            GtmFinding(
                "gtm_query_stripped",
                "low",
                "Une redirection supprime les parametres d'URL",
                "La page redirige en retirant la query string. Les parametres "
                "?gtm_debug / ?gtm_auth / ?gtm_preview utilises par le mode "
                "previsualisation peuvent etre perdus sur ce trajet — a verifier "
                "manuellement.",
            )
        )

    out.sort(key=lambda finding: _SEV_ORDER[finding.severity])
    return tuple(out)


async def check_gtm(domain: str, *, allow_insecure: bool = False) -> GtmCheck:
    url = f"https://{domain.strip().lower().removeprefix('www.')}"
    now = datetime.now(UTC)
    try:
        page = await fetch_page(url, allow_insecure=allow_insecure)
    except httpx.HTTPError:
        return GtmCheck(error="fetch_error", checked_at=now)
    if page.status >= 400:
        return GtmCheck(error="http_error", checked_at=now)
    if "html" not in page.headers.get("content-type", "").lower():
        return GtmCheck(error="non_html", checked_at=now)
    return replace(analyze_gtm(page), checked_at=now)
