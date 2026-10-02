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

import logging
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import parse_qs, urlparse

from playwright.async_api import async_playwright

from app.services.gtm_check import GtmFinding, Severity

logger = logging.getLogger(__name__)

# Code stable exposé à la place du détail technique (journal Playwright, chemins disque).
HEADLESS_FAILED = "headless_failed"

_GTM_HOST_HINT = "googletagmanager.com"
_GA4_HOSTS = ("google-analytics.com", "analytics.google.com")
_ADS_HOSTS = ("googleadservices.com", "googleads.g.doubleclick.net")
_ADS_CONVERSION_PATH = re.compile(r"/pagead/(?:conversion|viewthroughconversion)/\d{6,}(?:/|$)")
_GA4_ID_RE = re.compile(r"^G-[A-Z0-9]{4,20}$")
_MAX_GA4_IDS = 10
_CSP_HINT = "content security policy"
# Chrome imprime la ressource bloquee entre apostrophes en tete du message
# ("Refused to load the script 'https://...'" / "Loading the script '...'
# violates ..."). Le reste du message cite aussi la directive CSP complete,
# qui peut *autoriser* googletagmanager.com sans que ce soit lui le bloque
# (ex : un autre host tiers refuse alors que GTM est dans la liste
# d'autorisation) — d'ou l'extraction de la ressource plutot qu'un simple
# `in` sur le message entier.
_BLOCKED_URL_RE = re.compile(r"'([^']*)'")
_SEVERITIES = ("low", "medium", "high")


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
    ga4_measurement_ids: tuple[str, ...] = ()
    ads_requests: int = 0
    consent_default_seen: bool = False


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


def _is_ga4_collect(url: str) -> bool:
    return "/g/collect" in url and any(host in url for host in _GA4_HOSTS)


def _ga4_id_from_url(url: str) -> str | None:
    values = parse_qs(urlparse(url).query).get("tid")
    if not values or not _GA4_ID_RE.fullmatch(values[0]):
        return None
    return values[0]


def _record_ga4_id(ids: list[str], url: str) -> None:
    """Ajoute l'identifiant GA4 de `url` a `ids` (valide, sans doublon, plafonne)."""
    tid = _ga4_id_from_url(url)
    if tid and tid not in ids and len(ids) < _MAX_GA4_IDS:
        ids.append(tid)


def _is_ads_request(url: str) -> bool:
    """Requête de conversion Google Ads (avec identifiant AW dans le chemin).

    Les autres appels aux mêmes hôtes ne prouvent rien : un embed YouTube appelle
    `googleads.g.doubleclick.net/pagead/id` sans qu'aucune conversion du site existe."""
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if not any(host == h or host.endswith("." + h) for h in _ADS_HOSTS):
        return False
    return _ADS_CONVERSION_PATH.match(parsed.path) is not None


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
        "ga4_measurement_ids": list(result.ga4_measurement_ids),
        "ads_requests": result.ads_requests,
        "consent_default_seen": result.consent_default_seen,
    }


GtmHeadlessVerifier = Callable[[str], Awaitable[GtmHeadlessResult]]


def failed_headless_result() -> GtmHeadlessResult:
    """Résultat d'un navigateur qui n'a pas pu s'exécuter (local ou délégué au worker) :
    aucune observation, seul le code stable `HEADLESS_FAILED`."""
    return GtmHeadlessResult(
        gtm_js_loaded=False,
        containers_initialised=(),
        datalayer_present=False,
        gtm_events=(),
        requests_before_consent=False,
        csp_console_errors=(),
        findings=(),
        checked_at=datetime.now(UTC),
        error=HEADLESS_FAILED,
    )


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
    ga4_ids: list[str] = []
    ads_requests = 0
    consent_default_seen = False

    try:
        async with async_playwright() as pw:
            # Choix explicite : sous Cloud Run (gVisor) le bac à sable propre à Chromium ne
            # s'initialise pas ; l'isolement réel est celui du conteneur (utilisateur non
            # privilégié, Dockerfile.worker), du compte de service et du réseau.
            browser = await pw.chromium.launch(chromium_sandbox=False)
            try:
                page = await browser.new_page()

                def _on_request(request: Any) -> None:
                    nonlocal ads_requests
                    req_url = request.url
                    if _GTM_HOST_HINT in req_url:
                        requests_gtm.append(req_url)
                    if _is_ga4_collect(req_url):
                        _record_ga4_id(ga4_ids, req_url)
                    if _is_ads_request(req_url):
                        ads_requests += 1

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
                try:
                    consent_default_seen = bool(
                        await page.evaluate(
                            "Array.isArray(window.dataLayer) && window.dataLayer.some("
                            "e => e && e[0] === 'consent' && e[1] === 'default')"
                        )
                    )
                except Exception:  # pragma: no cover - jamais exerce en test
                    # Un echec ici ne doit pas annuler le reste du resultat.
                    consent_default_seen = False
            finally:
                await browser.close()
    except Exception as exc:  # pragma: no cover - jamais exerce en test (voir docstring)
        # Le detail (journal Playwright, chemins) reste dans les logs du serveur ; le
        # resultat n'expose qu'un code stable.
        logger.warning("Verification headless en echec pour %s: %s", url, type(exc).__name__)
        logger.debug("Detail de l'echec headless", exc_info=True)
        return failed_headless_result()

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
        ga4_measurement_ids=tuple(dict.fromkeys(ga4_ids)),
        ads_requests=ads_requests,
        consent_default_seen=consent_default_seen,
    )


def _flag(data: dict[str, Any], key: str) -> bool:
    value = data[key]
    if not isinstance(value, bool):
        raise ValueError(f"champ booléen attendu : {key}")
    return value


def _text(value: Any) -> str:
    if not isinstance(value, str):
        raise ValueError("chaîne attendue")
    return value


def _severity(value: Any) -> Severity:
    if value not in _SEVERITIES:
        raise ValueError("criticité inconnue")
    return value


def _strings(values: Any) -> tuple[str, ...]:
    if not isinstance(values, list) or not all(isinstance(v, str) for v in values):
        raise ValueError("liste de chaînes attendue")
    return tuple(values)


def headless_result_from_dict(data: Any) -> GtmHeadlessResult:
    """Inverse exact de `headless_result_to_dict` (réponse du service worker). Toute forme
    inattendue lève `ValueError` : l'appelant la traite comme un échec du navigateur."""
    if not isinstance(data, dict):
        raise ValueError("résultat headless illisible")
    try:
        findings_raw = data["findings"]
        if not isinstance(findings_raw, list) or not all(isinstance(f, dict) for f in findings_raw):
            raise ValueError("findings illisibles")
        findings = tuple(
            GtmFinding(
                code=_text(f["code"]),
                severity=_severity(f["severity"]),
                title=_text(f["title"]),
                detail=_text(f["detail"]),
            )
            for f in findings_raw
        )
        error = data.get("error")
        if error is not None:
            error = _text(error)
        ads_requests = data.get("ads_requests", 0)
        if isinstance(ads_requests, bool) or not isinstance(ads_requests, int):
            raise ValueError("ads_requests illisible")
        return GtmHeadlessResult(
            gtm_js_loaded=_flag(data, "gtm_js_loaded"),
            containers_initialised=_strings(data["containers_initialised"]),
            datalayer_present=_flag(data, "datalayer_present"),
            gtm_events=_strings(data["gtm_events"]),
            requests_before_consent=_flag(data, "requests_before_consent"),
            csp_console_errors=_strings(data["csp_console_errors"]),
            findings=findings,
            checked_at=datetime.fromisoformat(_text(data["checked_at"])),
            error=error,
            ga4_measurement_ids=_strings(data.get("ga4_measurement_ids", [])),
            ads_requests=ads_requests,
            consent_default_seen=_flag(data, "consent_default_seen")
            if "consent_default_seen" in data
            else False,
        )
    except (KeyError, TypeError) as exc:
        raise ValueError("résultat headless illisible") from exc
