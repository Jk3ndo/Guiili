from datetime import UTC, datetime

from app.services.gtm_check import GtmCheck
from app.services.gtm_headless import GtmHeadlessResult
from app.services.measurement.catalog import ITEMS, ITEMS_BY_ID
from app.services.measurement.checks import Facts, HeadlessFacts, evaluate, html_has_event


def _gtm(**kw) -> GtmCheck:
    base = {
        "containers": ("GTM-AAAA111",),
        "snippet_form": "standard",
        "snippet_in_head": True,
        "data_layer_name": "dataLayer",
    }
    base.update(kw)
    return GtmCheck(**base)


def _headless(**kw) -> HeadlessFacts:
    base = {
        "gtm_js_loaded": True,
        "containers": ("GTM-AAAA111",),
        "datalayer_events": (),
        "ga4_ids": (),
        "ads_requests": 0,
        "consent_default_seen": False,
        "checked_at": "2026-09-24T12:00:00+00:00",
    }
    base.update(kw)
    return HeadlessFacts(**base)


def _state(item_id: str, facts: Facts) -> str:
    return evaluate(ITEMS_BY_ID[item_id], facts).state


def test_html_has_event_patterns() -> None:
    assert html_has_event('dataLayer.push({event: "purchase"})', "purchase")
    assert html_has_event("dataLayer.push({ 'event' : 'purchase' })", "purchase")
    assert html_has_event("gtag('event', 'generate_lead', {})", "generate_lead")
    assert not html_has_event('var x = "purchase";', "purchase")
    assert not html_has_event('dataLayer.push({event: "purchase_x"})', "purchase")


def test_html_has_event_requires_the_event_key_boundary() -> None:
    assert not html_has_event('var prevent: "purchase"', "purchase")
    assert not html_has_event('x.event: "purchase"', "purchase")
    assert not html_has_event('mygtag("event", "purchase")', "purchase")


# ---- fondations -------------------------------------------------------------
def test_gtm_installed_states() -> None:
    assert _state("gtm_installed", Facts(gtm=_gtm())) == "on_page"
    assert _state("gtm_installed", Facts(gtm=GtmCheck(snippet_form="absent"))) == "missing"
    assert (
        _state("gtm_installed", Facts(gtm=GtmCheck(containers=("GTM-A1B2C3",), snippet_form="noscript_only")))
        == "missing"
    )
    unverifiable = evaluate(ITEMS_BY_ID["gtm_installed"], Facts(page_error="fetch_error"))
    assert unverifiable.state == "unverifiable" and unverifiable.reason == "fetch_error"


def test_gtm_installed_but_not_loaded_in_a_real_browser_is_missing() -> None:
    facts = Facts(gtm=_gtm(), headless=_headless(gtm_js_loaded=False))
    outcome = evaluate(ITEMS_BY_ID["gtm_installed"], facts)
    assert outcome.state == "missing"
    assert outcome.reason == "gtm_not_loaded_in_browser"


def test_gtm_in_head() -> None:
    assert _state("gtm_in_head", Facts(gtm=_gtm(snippet_in_head=True))) == "on_page"
    assert _state("gtm_in_head", Facts(gtm=_gtm(snippet_in_head=False))) == "missing"
    assert _state("gtm_in_head", Facts(gtm=_gtm(snippet_in_head=None))) == "unverifiable"
    assert _state("gtm_in_head", Facts(gtm=GtmCheck(snippet_form="absent"))) == "missing"


def test_ga4_tag_levels() -> None:
    hardcoded = _gtm(ga4_tags=("G-AAAA1111",))
    # GA4 connecté : reçu > présent > manquant
    assert (
        _state("ga4_tag", Facts(gtm=hardcoded, ga4_stats={"page_view": {"count": 50.0}}))
        == "received"
    )
    assert _state("ga4_tag", Facts(gtm=hardcoded, ga4_stats={})) == "on_page"
    assert _state("ga4_tag", Facts(gtm=_gtm(), ga4_stats={})) == "missing"
    # GA4 non connecté : jamais « reçu »
    assert _state("ga4_tag", Facts(gtm=hardcoded, ga4_reason="ga4_not_connected")) == "on_page"
    seen = Facts(gtm=_gtm(), headless=_headless(ga4_ids=("G-AAAA1111",)))
    assert _state("ga4_tag", seen) == "on_page"
    assert _state("ga4_tag", Facts(gtm=_gtm(), headless=_headless())) == "missing"
    undecided = evaluate(ITEMS_BY_ID["ga4_tag"], Facts(gtm=_gtm(), ga4_reason="ga4_not_connected"))
    assert undecided.state == "unverifiable" and undecided.reason == "headless_not_run"


def test_no_double_tracking() -> None:
    assert _state("no_double_tracking", Facts(gtm=_gtm(ga4_tags=("G-AAAA1111",)))) == "missing"
    assert _state("no_double_tracking", Facts(gtm=_gtm())) == "on_page"
    assert (
        _state("no_double_tracking", Facts(gtm=GtmCheck(snippet_form="absent"))) == "not_applicable"
    )


def test_consent_mode() -> None:
    cmp_only = Facts(
        page_html="<html></html>", gtm=_gtm(consent_platform="cookiebot"), headless=_headless()
    )
    assert _state("consent_mode", cmp_only) == "missing"
    complete = Facts(
        page_html="<html></html>",
        gtm=_gtm(consent_platform="cookiebot"),
        headless=_headless(consent_default_seen=True),
    )
    assert _state("consent_mode", complete) == "on_page"
    in_html = Facts(
        page_html="gtag('consent', 'default', {})", gtm=_gtm(consent_platform="axeptio")
    )
    assert _state("consent_mode", in_html) == "on_page"
    no_cmp = Facts(page_html="<html></html>", gtm=_gtm(), headless=_headless())
    assert _state("consent_mode", no_cmp) == "missing"
    unknown = evaluate(
        ITEMS_BY_ID["consent_mode"],
        Facts(page_html="<html></html>", gtm=_gtm(consent_platform="didomi")),
    )
    assert unknown.state == "unverifiable" and unknown.reason == "headless_not_run"


def test_consent_absence_is_never_stated_without_a_real_browser() -> None:
    # Sans navigateur, ni CMP détecté ni « consent default » dans le HTML ne prouve
    # l'absence : un CMP à modèle GTM ne pousse rien dans le HTML.
    bare = Facts(page_html="<html></html>", gtm=_gtm())
    outcome = evaluate(ITEMS_BY_ID["consent_mode"], bare)
    assert outcome.state == "unverifiable" and outcome.reason == "headless_not_run"


def test_consent_missing_after_a_real_browser_run_is_flagged_as_not_seen() -> None:
    facts = Facts(
        page_html="<html></html>", gtm=_gtm(consent_platform="cookiebot"), headless=_headless()
    )
    outcome = evaluate(ITEMS_BY_ID["consent_mode"], facts)
    assert outcome.state == "missing"
    assert outcome.reason == "consent_default_not_seen"


def test_datalayer_standard() -> None:
    assert _state("datalayer_standard", Facts(gtm=_gtm())) == "on_page"
    assert _state("datalayer_standard", Facts(gtm=_gtm(data_layer_name="appLayer"))) == "missing"
    assert (
        _state("datalayer_standard", Facts(gtm=GtmCheck(snippet_form="absent"))) == "not_applicable"
    )


def test_page_fetch_failure_is_unverifiable_never_missing() -> None:
    # `check_gtm` renvoie `GtmCheck(error=...)` quand la page n'a pas pu être lue :
    # le défaut `snippet_form="absent"` ne doit surtout pas se lire « GTM manquant ».
    for error in ("fetch_error", "http_error", "non_html"):
        facts = Facts(gtm=GtmCheck(error=error))
        for item_id in (
            "gtm_installed",
            "gtm_in_head",
            "no_double_tracking",
            "consent_mode",
            "datalayer_standard",
        ):
            outcome = evaluate(ITEMS_BY_ID[item_id], facts)
            assert outcome.state == "unverifiable", (error, item_id)
            assert outcome.reason == error, (error, item_id)


# ---- événements -------------------------------------------------------------
def test_event_levels_with_ga4() -> None:
    received = Facts(ga4_stats={"generate_lead": {"count": 4.0}})
    assert _state("event_generate_lead", received) == "received"
    found_in_code = Facts(
        page_html='dataLayer.push({event: "generate_lead"})', ga4_stats={}
    )
    assert _state("event_generate_lead", found_in_code) == "on_page"
    assert _state("event_generate_lead", Facts(ga4_stats={})) == "missing"


def test_event_without_ga4_is_never_received() -> None:
    facts = Facts(page_html='gtag("event", "generate_lead")', ga4_reason="ga4_not_connected")
    assert _state("event_generate_lead", facts) == "on_page"
    undecided = evaluate(ITEMS_BY_ID["event_generate_lead"], Facts(ga4_reason="ga4_not_connected"))
    assert undecided.state == "unverifiable"
    assert undecided.reason == "ga4_not_connected"


def test_event_seen_in_headless_datalayer_counts_as_on_page() -> None:
    facts = Facts(
        ga4_stats={}, headless=_headless(datalayer_events=("view_item",)), page_html=""
    )
    assert _state("event_view_item", facts) == "on_page"


def test_events_are_keyed_by_the_catalog_arg_not_the_item_id() -> None:
    # `event_outbound_click` mesure l'événement GA4 « click », pas « outbound_click ».
    item = ITEMS_BY_ID["event_outbound_click"]
    assert evaluate(item, Facts(ga4_stats={"click": {"count": 3.0}})).state == "received"
    assert evaluate(item, Facts(ga4_stats={"outbound_click": {"count": 3.0}})).state == "missing"


def test_purchase_params() -> None:
    ok = Facts(ga4_stats={"purchase": {"count": 3.0, "revenue": 120.0, "value": 0.0}})
    assert _state("purchase_params", ok) == "received"
    zero = Facts(ga4_stats={"purchase": {"count": 3.0, "revenue": 0.0, "value": 0.0}})
    assert _state("purchase_params", zero) == "missing"
    none = evaluate(ITEMS_BY_ID["purchase_params"], Facts(ga4_stats={}))
    assert none.state == "unverifiable" and none.reason == "purchase_not_received"
    off = evaluate(ITEMS_BY_ID["purchase_params"], Facts(ga4_reason="ga4_not_connected"))
    assert off.state == "unverifiable" and off.reason == "ga4_not_connected"


# ---- conversions ------------------------------------------------------------
def test_key_events_depend_on_the_site_type() -> None:
    events = [{"eventName": "generate_lead", "defaultValue": {"numericValue": 50}}]
    lead = Facts(key_events=events, effective_types=("lead_gen",))
    assert _state("key_events_marked", lead) == "received"
    assert _state("conversion_value", lead) == "received"
    shop = Facts(key_events=events, effective_types=("ecommerce",))
    assert _state("key_events_marked", shop) == "missing"
    no_value = Facts(
        key_events=[{"eventName": "generate_lead"}], effective_types=("lead_gen",)
    )
    assert _state("conversion_value", no_value) == "missing"
    down = evaluate(ITEMS_BY_ID["key_events_marked"], Facts(key_events_reason="quota"))
    assert down.state == "unverifiable" and down.reason == "quota"


# ---- publicité --------------------------------------------------------------
def test_ads_link_and_conversion_tag() -> None:
    assert _state("ads_ga4_link", Facts(ads_links_count=1)) == "received"
    assert _state("ads_ga4_link", Facts(ads_links_count=0)) == "missing"
    assert _state("ads_ga4_link", Facts(ads_links_reason="ga4_not_connected")) == "unverifiable"

    in_html = Facts(page_html="gtag('config', 'AW-123456789')")
    assert _state("ads_conversion_tag", in_html) == "on_page"
    seen = Facts(page_html="", headless=_headless(ads_requests=2))
    assert _state("ads_conversion_tag", seen) == "on_page"
    absent = Facts(page_html="", headless=_headless())
    assert _state("ads_conversion_tag", absent) == "missing"
    undecided = evaluate(ITEMS_BY_ID["ads_conversion_tag"], Facts(page_html=""))
    assert undecided.state == "unverifiable" and undecided.reason == "headless_not_run"


def test_manual_items_need_the_owner_confirmation() -> None:
    item = ITEMS_BY_ID["ads_auto_tagging"]
    todo = evaluate(item, Facts())
    assert todo.state == "unverifiable" and todo.reason == "manual_check"
    done = evaluate(item, Facts(manual_done=frozenset({"ads_auto_tagging"})))
    assert done.state == "on_page"
    assert done.evidence == {"manual_done": True}


# ---- SEO --------------------------------------------------------------------
def test_seo_checks() -> None:
    assert _state("gsc_property_linked", Facts(gsc_state="linked")) == "received"
    assert _state("gsc_property_linked", Facts(gsc_state="not_linked")) == "missing"
    stale = evaluate(ITEMS_BY_ID["gsc_property_linked"], Facts(gsc_state="needs_reauth"))
    assert stale.state == "unverifiable" and stale.reason == "connection_needs_reauth"

    assert _state("gsc_sitemaps", Facts(sitemaps_count=2)) == "received"
    assert _state("gsc_sitemaps", Facts(sitemaps_count=0)) == "missing"
    assert _state("gsc_sitemaps", Facts(sitemaps_reason="gsc_not_connected")) == "unverifiable"

    assert _state("robots_txt", Facts(robots_ok=True)) == "on_page"
    assert _state("robots_txt", Facts(robots_ok=False)) == "missing"
    assert _state("robots_txt", Facts(robots_ok=None)) == "unverifiable"

    assert _state("tls_valid", Facts(ssl_status="valid")) == "on_page"
    assert _state("tls_valid", Facts(ssl_status="expiring_soon")) == "on_page"
    assert _state("tls_valid", Facts(ssl_status="expired")) == "missing"
    assert _state("tls_valid", Facts(ssl_status=None)) == "unverifiable"


def test_unexpected_google_response_is_unverifiable_never_missing_nor_received() -> None:
    # Une réponse de forme inattendue lève GoogleReadError("api_error") ; l'appelant la
    # traduit en `*_reason="api_error"` et laisse la donnée à None.
    api_error = Facts(
        ga4_reason="api_error",
        key_events_reason="api_error",
        ads_links_reason="api_error",
        sitemaps_reason="api_error",
    )
    for item_id in (
        "event_generate_lead",
        "purchase_params",
        "key_events_marked",
        "conversion_value",
        "ads_ga4_link",
        "gsc_sitemaps",
    ):
        outcome = evaluate(ITEMS_BY_ID[item_id], api_error)
        assert outcome.state == "unverifiable", item_id
        assert outcome.reason == "api_error", item_id


def test_every_catalog_item_evaluates_on_empty_facts() -> None:
    # Filet : aucun `check` du catalogue ne doit manquer au moteur.
    for item in ITEMS:
        assert evaluate(item, Facts()).state in {
            "missing",
            "unverifiable",
            "not_applicable",
            "on_page",
            "received",
        }, item.id


def test_headless_facts_roundtrip_and_conversion() -> None:
    result = GtmHeadlessResult(
        gtm_js_loaded=True,
        containers_initialised=("GTM-AAAA111",),
        datalayer_present=True,
        gtm_events=("page_view",),
        requests_before_consent=True,
        csp_console_errors=(),
        findings=(),
        checked_at=datetime(2026, 9, 24, 12, 0, tzinfo=UTC),
        ga4_measurement_ids=("G-ABC123XYZ",),
        ads_requests=1,
        consent_default_seen=True,
    )
    facts = HeadlessFacts.from_result(result)
    assert facts.ga4_ids == ("G-ABC123XYZ",)
    assert HeadlessFacts.from_dict(facts.to_dict()) == facts
    assert HeadlessFacts.from_dict({}) is None
    assert HeadlessFacts.from_dict({"gtm_js_loaded": True}) is not None  # tolère l'ancien format
