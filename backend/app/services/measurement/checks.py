"""Moteur de vérification : `evaluate(item, facts) -> Outcome`, fonction pure.

L'état d'un item est le niveau de preuve le plus haut atteint (`received` > `on_page`
> `missing`). Une preuve inaccessible donne `unverifiable` avec une `reason` — jamais
`missing`, jamais « fait ». Les items sont repérés par `item.id` (jamais déduits de
`arg`) ; `arg` ne sert qu'à nommer l'événement GA4 mesuré.

Limites connues, à ne pas présenter comme des preuves d'absence :
- `consent_default_seen` ne voit que les `consent default` poussés dans le dataLayer :
  un CMP à modèle GTM peut le définir sans qu'on le voie.
- Une absence vue par le navigateur headless n'est jamais une preuve : il ne clique pas la
  bannière de consentement (un CMP peut bloquer les balises) et une balise de conversion
  Ads ne se déclenche que sur son événement, pas sur la page d'accueil.
- `ga4_tag` et `gtm_in_head` supposent implicitement que GTM est installé
  (`gtm_installed`) : sans conteneur, `gtm_in_head` vaut « manquant » (`gtm_absent`).
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from typing import Any

from app.services.gtm_check import GtmCheck
from app.services.gtm_headless import GtmHeadlessResult
from app.services.measurement.types import MeasurementItem, Outcome

_AW_ID = re.compile(r"AW-\d{6,}")
_CONSENT_DEFAULT = re.compile(r"""['"]consent['"]\s*,\s*['"]default['"]""")

# Événements clés attendus selon le type de site.
_KEY_EVENTS_BY_TYPE: dict[str, frozenset[str]] = {
    "ecommerce": frozenset({"purchase"}),
    "lead_gen": frozenset({"generate_lead"}),
    "saas": frozenset({"sign_up", "begin_trial", "subscribe"}),
    "content": frozenset({"newsletter_signup"}),
}

# Statuts de `tls_check` : le certificat est prouvé sain, ou prouvé mauvais. Tout le reste
# (« unreachable », inconnu) est une absence d'observation.
_TLS_OK = frozenset({"valid", "expiring_soon"})
_TLS_BAD = frozenset({"expired", "self_signed", "hostname_mismatch", "untrusted"})

_PAGE_KINDS = frozenset({"gtm_installed", "gtm_in_head", "no_double", "datalayer"})


@dataclass(frozen=True, slots=True)
class HeadlessFacts:
    gtm_js_loaded: bool
    containers: tuple[str, ...]
    datalayer_events: tuple[str, ...]
    ga4_ids: tuple[str, ...]
    ads_requests: int
    consent_default_seen: bool
    checked_at: str  # ISO 8601

    @classmethod
    def from_result(cls, result: GtmHeadlessResult) -> HeadlessFacts | None:
        """`None` si le navigateur a échoué : `verify_gtm` renvoie alors un résultat aux
        valeurs par défaut, qui se lirait à tort « GTM non chargé »."""
        if result.error is not None:
            return None
        return cls(
            gtm_js_loaded=result.gtm_js_loaded,
            containers=tuple(result.containers_initialised),
            datalayer_events=tuple(result.gtm_events),
            ga4_ids=tuple(result.ga4_measurement_ids),
            ads_requests=result.ads_requests,
            consent_default_seen=result.consent_default_seen,
            checked_at=result.checked_at.isoformat(),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "gtm_js_loaded": self.gtm_js_loaded,
            "containers": list(self.containers),
            "datalayer_events": list(self.datalayer_events),
            "ga4_ids": list(self.ga4_ids),
            "ads_requests": self.ads_requests,
            "consent_default_seen": self.consent_default_seen,
            "checked_at": self.checked_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> HeadlessFacts | None:
        if not data:
            return None
        return cls(
            gtm_js_loaded=bool(data.get("gtm_js_loaded", False)),
            containers=tuple(data.get("containers", ())),
            datalayer_events=tuple(data.get("datalayer_events", ())),
            ga4_ids=tuple(data.get("ga4_ids", ())),
            ads_requests=int(data.get("ads_requests", 0)),
            consent_default_seen=bool(data.get("consent_default_seen", False)),
            checked_at=str(data.get("checked_at", "")),
        )


@dataclass(frozen=True, slots=True)
class Facts:
    """Tout ce que les vérifications ont le droit de savoir sur un site."""

    page_html: str | None = None
    page_error: str | None = None
    gtm: GtmCheck | None = None
    headless: HeadlessFacts | None = None
    ga4_stats: dict[str, dict[str, float]] | None = None
    ga4_reason: str | None = None
    key_events: list[dict[str, Any]] | None = None
    key_events_reason: str | None = None
    ads_links_count: int | None = None
    ads_links_reason: str | None = None
    # « needs_reauth » couvre aussi un échec réseau transitoire du rafraîchissement du
    # jeton (la connexion reste ACTIVE) : à formuler « à revérifier », pas « révoquée ».
    gsc_state: str = "not_linked"
    sitemaps_count: int | None = None
    sitemaps_reason: str | None = None
    robots_ok: bool | None = None
    robots_reason: str | None = None
    ssl_status: str | None = None
    ssl_checked_at: str | None = None  # ISO 8601, date du dernier contrôle du certificat
    effective_types: tuple[str, ...] = ("other",)
    manual_done: frozenset[str] = field(default_factory=frozenset)


def html_has_event(html: str, name: str) -> bool:
    n = re.escape(name)
    pattern = (
        rf"""(?:(?<![\w$.])['"]?event['"]?\s*:\s*['"]{n}['"]"""
        rf"""|(?<![\w$.])gtag\(\s*['"]event['"]\s*,\s*['"]{n}['"])"""
    )
    return re.search(pattern, html) is not None


def _unverifiable(reason: str) -> Outcome:
    return Outcome("unverifiable", {}, reason)


def _consent_may_block(f: Facts) -> bool:
    """Vrai si un CMP est reconnu ou un `consent default` est visible (HTML ou navigateur) :
    le navigateur headless ne clique pas la bannière, donc les balises soumises au
    consentement peuvent ne jamais partir sans que le site soit fautif."""
    if f.gtm is not None and f.gtm.consent_platform:
        return True
    if f.headless is not None and f.headless.consent_default_seen:
        return True
    return bool(f.page_html and _CONSENT_DEFAULT.search(f.page_html))


# ---- fondations ---------------------------------------------------------------
def _gtm_installed(item: MeasurementItem, f: Facts) -> Outcome:
    gtm = f.gtm
    if gtm is None:
        return _unverifiable(f.page_error or "page_unavailable")
    installed = gtm.snippet_form in ("standard", "custom_loader") and bool(gtm.containers)
    evidence: dict[str, Any] = {
        "containers": list(gtm.containers),
        "snippet_form": gtm.snippet_form,
    }
    if f.headless is not None:
        evidence["headless_loaded"] = f.headless.gtm_js_loaded
        if installed and not f.headless.gtm_js_loaded:
            return Outcome("missing", evidence, "gtm_not_loaded_in_browser")
    return Outcome("on_page" if installed else "missing", evidence, None)


def _gtm_in_head(item: MeasurementItem, f: Facts) -> Outcome:
    gtm = f.gtm
    if gtm is None:
        return _unverifiable(f.page_error or "page_unavailable")
    if not gtm.containers:
        return Outcome("missing", {}, "gtm_absent")
    if gtm.snippet_in_head is True:
        return Outcome("on_page", {"snippet_in_head": True}, None)
    if gtm.snippet_in_head is False:
        return Outcome("missing", {"snippet_in_head": False}, None)
    return _unverifiable("position_unknown")


def _ga4_tag(item: MeasurementItem, f: Facts) -> Outcome:
    hardcoded = tuple(f.gtm.ga4_tags) if f.gtm else ()
    seen = f.headless.ga4_ids if f.headless else ()
    evidence: dict[str, Any] = {}
    if hardcoded:
        evidence["hardcoded_ids"] = list(hardcoded)
    if seen:
        evidence["seen_ids"] = list(seen)
    on_page = bool(hardcoded or seen)

    if f.ga4_stats is not None:
        page_views = f.ga4_stats.get("page_view", {}).get("count", 0.0)
        if page_views > 0:
            return Outcome("received", {**evidence, "page_views_30d": int(page_views)}, None)
        # GA4 connecté mais sans page_view : délai de traitement (~48 h) ou mauvaise
        # propriété liée ; le compteur à 0 permet à l'interface de nuancer.
        return Outcome(
            "on_page" if on_page else "missing", {**evidence, "page_views_30d": 0}, None
        )
    if on_page:
        return Outcome("on_page", evidence, None)
    if f.headless is not None:
        if _consent_may_block(f):
            # Rien n'est parti, mais le consentement par défaut est « refusé » et personne
            # n'a cliqué la bannière : ce n'est pas une preuve d'absence.
            return _unverifiable("consent_may_block_tags")
        return Outcome("missing", evidence, None)
    return _unverifiable("headless_not_run")


def _no_double(item: MeasurementItem, f: Facts) -> Outcome:
    gtm = f.gtm
    if gtm is None:
        return _unverifiable(f.page_error or "page_unavailable")
    hardcoded, has_gtm = bool(gtm.ga4_tags), bool(gtm.containers)
    if hardcoded and has_gtm:
        return Outcome(
            "missing",
            {"hardcoded_ids": list(gtm.ga4_tags), "containers": list(gtm.containers)},
            None,
        )
    if not hardcoded and not has_gtm:
        return Outcome("not_applicable", {}, "gtm_absent")
    return Outcome("on_page", {}, None)


def _consent(item: MeasurementItem, f: Facts) -> Outcome:
    if f.gtm is None:
        return _unverifiable(f.page_error or "page_unavailable")
    cmp_name = f.gtm.consent_platform
    in_html = bool(f.page_html and _CONSENT_DEFAULT.search(f.page_html))
    in_browser = bool(f.headless and f.headless.consent_default_seen)
    default_seen = in_html or in_browser
    evidence = {"cmp": cmp_name, "consent_default": default_seen}
    if cmp_name and default_seen:
        return Outcome("on_page", evidence, None)
    if f.headless is None:
        # Sans navigateur, l'absence de « consent default » dans le HTML ne prouve rien.
        return Outcome("unverifiable", evidence, "headless_not_run")
    if default_seen:
        # Consent Mode vu mais aucun CMP reconnu : sans conteneur GTM, `consent_platform`
        # n'est pas analysé, et la liste des CMP connus est finie. Jamais « manquant ».
        return Outcome("unverifiable", evidence, "cmp_not_detected")
    if cmp_name:
        # « Non vu » n'est pas « absent » : un CMP à modèle GTM ne pousse rien dans le
        # dataLayer, donc son consentement par défaut échappe à cette détection.
        return Outcome("unverifiable", evidence, "cmp_default_not_observed")
    return Outcome("missing", evidence, "consent_default_not_seen")


def _datalayer(item: MeasurementItem, f: Facts) -> Outcome:
    gtm = f.gtm
    if gtm is None:
        return _unverifiable(f.page_error or "page_unavailable")
    if not gtm.containers:
        return Outcome("not_applicable", {}, "gtm_absent")
    evidence = {"data_layer_name": gtm.data_layer_name}
    return Outcome("on_page" if gtm.data_layer_name == "dataLayer" else "missing", evidence, None)


# ---- événements ---------------------------------------------------------------
def _on_page_event(name: str, f: Facts) -> str | None:
    if f.page_html and html_has_event(f.page_html, name):
        return "html"
    if f.headless and name in f.headless.datalayer_events:
        return "headless_datalayer"
    return None


def _event(item: MeasurementItem, f: Facts) -> Outcome:
    name = item.arg or ""
    found_in = _on_page_event(name, f)
    evidence: dict[str, Any] = {"found_in": found_in} if found_in else {}
    if f.ga4_stats is not None:
        count = f.ga4_stats.get(name, {}).get("count", 0.0)
        if count > 0:
            return Outcome("received", {**evidence, "ga4_count_30d": int(count)}, None)
        if found_in:
            return Outcome("on_page", {**evidence, "ga4_count_30d": 0}, None)
        return Outcome("missing", {"ga4_count_30d": 0}, None)
    if found_in:
        return Outcome("on_page", evidence, None)
    return _unverifiable(f.ga4_reason or "ga4_not_connected")


def _purchase_params(item: MeasurementItem, f: Facts) -> Outcome:
    if f.ga4_stats is None:
        return _unverifiable(f.ga4_reason or "ga4_not_connected")
    purchase = f.ga4_stats.get("purchase", {})
    if purchase.get("count", 0.0) <= 0:
        return _unverifiable("purchase_not_received")
    evidence = {
        "purchases_30d": int(purchase["count"]),
        "revenue_30d": purchase.get("revenue", 0.0),
    }
    if purchase.get("revenue", 0.0) > 0 or purchase.get("value", 0.0) > 0:
        return Outcome("received", evidence, None)
    return Outcome("missing", evidence, None)


# ---- conversions --------------------------------------------------------------
def _expected_key_events(types: tuple[str, ...]) -> frozenset[str]:
    names: set[str] = set()
    for site_type in types:
        names |= _KEY_EVENTS_BY_TYPE.get(site_type, frozenset())
    return frozenset(names)


def _valued(entry: dict[str, Any]) -> bool | None:
    """Vrai/faux si l'événement a une valeur par défaut > 0 ; `None` si la forme est
    inattendue (l'API Google est censée renvoyer un objet `{numericValue: nombre}`)."""
    default = entry.get("defaultValue")
    if default is None:
        return False
    if not isinstance(default, dict):
        return None
    number = default.get("numericValue", 0)
    if number is None:
        return False
    try:
        return float(number) > 0
    except (TypeError, ValueError):
        return None


def _key_events(item: MeasurementItem, f: Facts) -> Outcome:
    if f.key_events is None:
        return _unverifiable(f.key_events_reason or "ga4_not_connected")
    entries = [e for e in f.key_events if isinstance(e, dict)]
    declared = [e.get("eventName") for e in entries if e.get("eventName")]
    expected = _expected_key_events(f.effective_types)
    matching = [name for name in declared if name in expected] if expected else declared
    if not matching and len(entries) != len(f.key_events):
        return _unverifiable("api_error")
    evidence = {"key_events": declared}
    return Outcome("received" if matching else "missing", evidence, None)


def _key_events_value(item: MeasurementItem, f: Facts) -> Outcome:
    if f.key_events is None:
        return _unverifiable(f.key_events_reason or "ga4_not_connected")
    expected = _expected_key_events(f.effective_types)
    valued: list[str] = []
    malformed = len([e for e in f.key_events if not isinstance(e, dict)])
    for entry in (e for e in f.key_events if isinstance(e, dict)):
        name = entry.get("eventName")
        if expected and name not in expected:
            continue
        result = _valued(entry)
        if result is None:
            malformed += 1
        elif result:
            valued.append(name)
    if valued:
        return Outcome("received", {"valued_events": valued}, None)
    if malformed:
        # Une réponse de forme inattendue n'est ni « reçue » ni « manquante ».
        return _unverifiable("api_error")
    return Outcome("missing", {"valued_events": valued}, None)


# ---- publicité ----------------------------------------------------------------
def _ads_link(item: MeasurementItem, f: Facts) -> Outcome:
    if f.ads_links_count is None:
        return _unverifiable(f.ads_links_reason or "ga4_not_connected")
    evidence = {"ads_links": f.ads_links_count}
    return Outcome("received" if f.ads_links_count > 0 else "missing", evidence, None)


def _ads_conversion_tag(item: MeasurementItem, f: Facts) -> Outcome:
    ids = sorted(set(_AW_ID.findall(f.page_html or "")))
    ads_requests = f.headless.ads_requests if f.headless else 0
    evidence: dict[str, Any] = {}
    if ids:
        evidence["ads_ids"] = ids
    if ads_requests > 0:
        evidence["ads_requests"] = ads_requests
    if ids or ads_requests > 0:
        return Outcome("on_page", evidence, None)
    if f.headless is None:
        return _unverifiable("headless_not_run")
    # Une balise de conversion (importée via notre conteneur) ne se déclenche que sur
    # l'événement de conversion : son absence sur la page d'accueil n'est jamais une
    # preuve. Seule une présence (AW-<id> ou requête de conversion) se prouve.
    if _consent_may_block(f):
        return _unverifiable("consent_may_block_tags")
    return _unverifiable("ads_conversion_needs_event")


def _manual(item: MeasurementItem, f: Facts) -> Outcome:
    if item.id in f.manual_done:
        return Outcome("on_page", {"manual_done": True}, None)
    return _unverifiable("manual_check")


# ---- SEO ----------------------------------------------------------------------
def _gsc_linked(item: MeasurementItem, f: Facts) -> Outcome:
    if f.gsc_state == "linked":
        return Outcome("received", {}, None)
    if f.gsc_state == "needs_reauth":
        return _unverifiable("connection_needs_reauth")
    return Outcome("missing", {}, None)


def _gsc_sitemaps(item: MeasurementItem, f: Facts) -> Outcome:
    if f.sitemaps_count is None:
        return _unverifiable(f.sitemaps_reason or "gsc_not_connected")
    evidence = {"sitemaps": f.sitemaps_count}
    return Outcome("received" if f.sitemaps_count > 0 else "missing", evidence, None)


def _robots(item: MeasurementItem, f: Facts) -> Outcome:
    if f.robots_ok is None:
        return _unverifiable(f.robots_reason or "not_checked")
    return Outcome("on_page" if f.robots_ok else "missing", {"robots_ok": f.robots_ok}, None)


def _tls(item: MeasurementItem, f: Facts) -> Outcome:
    if f.ssl_status is None:
        return _unverifiable("not_checked")
    evidence: dict[str, Any] = {"ssl_status": f.ssl_status}
    if f.ssl_checked_at:
        evidence["checked_at"] = f.ssl_checked_at
    if f.ssl_status in _TLS_OK:
        return Outcome("on_page", evidence, None)
    if f.ssl_status in _TLS_BAD:
        return Outcome("missing", evidence, None)
    # « unreachable » (timeout, DNS) ou statut inconnu : on n'a rien constaté du certificat.
    return Outcome("unverifiable", evidence, "tls_unreachable")


_CHECKS: dict[str, Callable[[MeasurementItem, Facts], Outcome]] = {
    "gtm_installed": _gtm_installed,
    "gtm_in_head": _gtm_in_head,
    "ga4_tag": _ga4_tag,
    "no_double": _no_double,
    "consent": _consent,
    "datalayer": _datalayer,
    "event": _event,
    "purchase_params": _purchase_params,
    "key_events": _key_events,
    "key_events_value": _key_events_value,
    "ads_link": _ads_link,
    "ads_conversion_tag": _ads_conversion_tag,
    "manual": _manual,
    "gsc_linked": _gsc_linked,
    "gsc_sitemaps": _gsc_sitemaps,
    "robots": _robots,
    "tls": _tls,
}


def evaluate(item: MeasurementItem, facts: Facts) -> Outcome:
    # `check_gtm` renvoie `GtmCheck(error=...)` quand la page n'a pas pu être lue : ses
    # valeurs par défaut (snippet « absent ») ne sont pas une observation. On le traite
    # comme une page inaccessible plutôt que de conclure « GTM manquant ».
    if facts.gtm is not None and facts.gtm.error is not None:
        facts = replace(facts, gtm=None, page_error=facts.page_error or facts.gtm.error)
    if item.check in _PAGE_KINDS and facts.page_error is not None and facts.gtm is None:
        return _unverifiable(facts.page_error)
    return _CHECKS[item.check](item, facts)
