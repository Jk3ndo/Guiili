"""Verification headless (Playwright) de la configuration GTM en conditions reelles.

Complete `gtm_check.analyze_gtm` (statique, HTML + en-tetes) par une passe dans
un vrai navigateur Chromium : le snippet GTM se charge-t-il reellement, le
conteneur s'initialise-t-il, `dataLayer` existe-t-il, la CSP bloque-t-elle
effectivement `googletagmanager.com` en conditions reelles ? Confirme ou
infirme les findings statiques (`csp_blocks_preview`, `gtm_consent_gated`...).

`verify_gtm` lance un vrai navigateur — **jamais appele dans la suite de
tests** (necessite Chromium). Injecte via `app.api.deps.get_gtm_headless_verifier`,
overridee en test par une fonction factice. `_derive_findings` et
`headless_result_to_dict` sont pures et testees directement.

Limite connue v1 : `requests_before_consent` n'attend/simule aucune
interaction avec une bannière de consentement (aucun clic automatise sur un
CMP generique n'est fiable inter-sites) — toute requete GTM observee au
chargement initial de la page compte comme "avant interaction utilisateur".
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from playwright.async_api import async_playwright

from app.services.gtm_check import GtmFinding

_GTM_HOST_HINT = "googletagmanager.com"
_CSP_HINT = "content security policy"
# Chrome imprime la ressource bloquee entre apostrophes en tete du message
# ("Refused to load the script 'https://...'" / "Loading the script '...'
# violates ..."). Le reste du message cite aussi la directive CSP complete,
# qui peut *autoriser* googletagmanager.com sans que ce soit lui le bloque
# (ex : un autre host tiers refuse alors que GTM est dans la liste
# d'autorisation) — d'ou l'extraction de la ressource plutot qu'un simple
# `in` sur le message entier.
_BLOCKED_URL_RE = re.compile(r"'([^']*)'")


@dataclass(frozen=True, slots=True)
class GtmHeadlessResult:
    gtm_js_loaded: bool
    containers_initialised: tuple[str, ...]
    datalayer_present: bool
    gtm_events: tuple[str, ...]
    requests_before_consent: bool
    csp_console_errors: tuple[str, ...]
    findings: tuple[GtmFinding, ...]
    checked_at: datetime
    error: str | None = None


def _is_gtm_csp_violation(message: str) -> bool:
    """True si `message` (un log console d'erreur) est un blocage CSP dont
    la ressource *refusee* est bien googletagmanager.com — pas seulement un
    message qui mentionne ce host en passant (ex : dans la liste des sources
    autorisees de la directive, imprimee par Chrome dans le meme message)."""
    lower = message.lower()
    if _CSP_HINT not in lower:
        return False
    match = _BLOCKED_URL_RE.search(message)
    blocked_url = match.group(1) if match else message
    return _GTM_HOST_HINT in blocked_url.lower()


def _derive_findings(
    *,
    gtm_js_loaded: bool,
    containers_initialised: tuple[str, ...],
    datalayer_present: bool,
    csp_console_errors: tuple[str, ...],
) -> tuple[GtmFinding, ...]:
    findings: list[GtmFinding] = []
    if not gtm_js_loaded:
        findings.append(
            GtmFinding(
                code="headless_gtm_not_loaded",
                severity="high",
                title="gtm.js ne se charge pas dans un vrai navigateur",
                detail=(
                    "Aucune requete vers googletagmanager.com pendant le chargement "
                    "de la page en conditions reelles — le conteneur ne peut pas "
                    "s'initialiser, quel que soit le diagnostic statique."
                ),
            )
        )
    elif not containers_initialised:
        findings.append(
            GtmFinding(
                code="headless_container_not_initialised",
                severity="high",
                title="gtm.js charge mais aucun conteneur ne s'initialise",
                detail=(
                    "window.google_tag_manager est vide apres chargement : le script "
                    "repond mais n'active aucun conteneur (id invalide, erreur JS en "
                    "amont dans la page)."
                ),
            )
        )
    if gtm_js_loaded and not datalayer_present:
        findings.append(
            GtmFinding(
                code="headless_datalayer_missing",
                severity="medium",
                title="dataLayer absent apres chargement de GTM",
                detail=(
                    "GTM se charge mais window.dataLayer n'existe pas en fin de "
                    "chargement — les evenements pousses avant l'init de GTM sont perdus."
                ),
            )
        )
    if csp_console_errors:
        findings.append(
            GtmFinding(
                code="headless_csp_blocks_gtm",
                severity="high",
                title="La CSP bloque effectivement GTM en conditions reelles",
                detail=(
                    "La console du navigateur rapporte un blocage CSP vers "
                    f"{_GTM_HOST_HINT} : " + "; ".join(csp_console_errors[:3])
                ),
            )
        )
    return tuple(findings)


def headless_result_to_dict(result: GtmHeadlessResult) -> dict[str, Any]:
    """Serialise vers la forme stockee dans `snapshot.metrics['gtm']['headless']`."""
    return {
        "gtm_js_loaded": result.gtm_js_loaded,
        "containers_initialised": list(result.containers_initialised),
        "datalayer_present": result.datalayer_present,
        "gtm_events": list(result.gtm_events),
        "requests_before_consent": result.requests_before_consent,
        "csp_console_errors": list(result.csp_console_errors),
        "findings": [
            {"code": f.code, "severity": f.severity, "title": f.title, "detail": f.detail}
            for f in result.findings
        ],
        "checked_at": result.checked_at.isoformat(),
        "error": result.error,
    }


GtmHeadlessVerifier = Callable[[str], Awaitable[GtmHeadlessResult]]


async def verify_gtm(url: str, *, timeout: float = 20.0) -> GtmHeadlessResult:
    """Charge `url` dans Chromium headless et observe le comportement reel de GTM.

    Ne leve jamais : toute erreur (navigation, timeout, navigateur indisponible)
    devient un `GtmHeadlessResult(error=...)`.
    """
    requests_gtm: list[str] = []
    console_errors: list[str] = []
    containers: list[str] = []
    datalayer_present = False
    gtm_events: list[str] = []

    try:
        async with async_playwright() as pw:
            browser = await pw.chromium.launch()
            try:
                page = await browser.new_page()

                def _on_request(request: Any) -> None:
                    if _GTM_HOST_HINT in request.url:
                        requests_gtm.append(request.url)

                def _on_console(msg: Any) -> None:
                    if msg.type == "error":
                        console_errors.append(msg.text)

                page.on("request", _on_request)
                page.on("console", _on_console)

                await page.goto(url, wait_until="networkidle", timeout=timeout * 1000)

                containers = list(
                    await page.evaluate("Object.keys(window.google_tag_manager || {})")
                )
                datalayer_present = bool(await page.evaluate("Array.isArray(window.dataLayer)"))
                raw_events = await page.evaluate("window.dataLayer || []")
                gtm_events = [
                    str(e["event"])
                    for e in raw_events
                    if isinstance(e, dict) and e.get("event")
                ]
            finally:
                await browser.close()
    except Exception as exc:  # pragma: no cover - jamais exerce en test (voir docstring)
        return GtmHeadlessResult(
            gtm_js_loaded=False,
            containers_initialised=(),
            datalayer_present=False,
            gtm_events=(),
            requests_before_consent=False,
            csp_console_errors=(),
            findings=(),
            checked_at=datetime.now(UTC),
            error=f"{type(exc).__name__}: {exc}",
        )

    csp_blocked = tuple(e for e in console_errors if _is_gtm_csp_violation(e))
    gtm_js_loaded = bool(requests_gtm)
    findings = _derive_findings(
        gtm_js_loaded=gtm_js_loaded,
        containers_initialised=tuple(containers),
        datalayer_present=datalayer_present,
        csp_console_errors=csp_blocked,
    )
    return GtmHeadlessResult(
        gtm_js_loaded=gtm_js_loaded,
        containers_initialised=tuple(containers),
        datalayer_present=datalayer_present,
        gtm_events=tuple(gtm_events),
        # Aucune simulation d'interaction CMP en v1 (voir docstring module) :
        # toute requete GTM au chargement initial compte comme "avant consentement".
        requests_before_consent=gtm_js_loaded,
        csp_console_errors=csp_blocked,
        findings=findings,
        checked_at=datetime.now(UTC),
    )
