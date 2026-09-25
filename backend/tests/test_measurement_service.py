import asyncio
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.enums import ConnectionStatus, ResourceType, StackKind
from app.models.google_connection import GoogleConnection
from app.models.measurement_item_event import MeasurementItemEvent
from app.models.measurement_item_status import MeasurementItemStatus
from app.models.user import User
from app.models.website import Website
from app.models.website_google_link import WebsiteGoogleLink
from app.models.website_profile import WebsiteProfile
from app.models.workspace import Workspace
from app.services.gtm_headless import GtmHeadlessResult
from app.services.measurement import fetch as fetch_module
from app.services.measurement.catalog import ITEMS
from app.services.measurement.google_reader import GoogleReadError
from app.services.measurement.service import (
    COOLDOWN,
    build_plan_view,
    refresh_plan,
)
from app.services.page_fetch import PageSnapshot
from tests.conftest import owner_workspace_id

_SHOP_HTML = """
<html><head>
<script>(function(w,d,s,l,i){w[l]=w[l]||[];w[l].push({'gtm.start':1,event:'gtm.js'});
var j=d.createElement(s);j.src='https://www.googletagmanager.com/gtm.js?id='+i;})
(window,document,'script','dataLayer','GTM-AAAA111');</script>
<script src="https://cdn.shopify.com/app.js"></script></head>
<body><button class="add-to-cart">Ajouter au panier</button></body></html>
"""


def _snapshot(url: str, html: str, status: int = 200, ctype: str = "text/html") -> PageSnapshot:
    return PageSnapshot(
        url=url,
        final_url=url,
        status=status,
        html=html,
        headers={"content-type": ctype},
        redirected=False,
        history=(),
    )


class _Fetcher:
    def __init__(
        self,
        html: str | None = _SHOP_HTML,
        robots_status: int = 200,
        robots_ctype: str = "text/plain",
        page_status: int = 200,
        page_ctype: str = "text/html",
    ) -> None:
        self.html = html
        self.robots_status = robots_status
        self.robots_ctype = robots_ctype
        self.page_status = page_status
        self.page_ctype = page_ctype
        self.calls: list[str] = []

    async def __call__(self, url: str, *, allow_insecure: bool = False):
        self.calls.append(url)
        if url.endswith("/robots.txt"):
            return _snapshot(url, "User-agent: *", self.robots_status, self.robots_ctype)
        if self.html is None:
            return None
        return _snapshot(url, self.html, self.page_status, self.page_ctype)


class _Reader:
    gsc_state = "not_linked"

    def __init__(self, **kw) -> None:
        self.stats = kw.get("stats")
        self.key = kw.get("key")
        self.ads = kw.get("ads")
        self.sitemaps = kw.get("sitemaps")
        self.gsc_state = kw.get("gsc_state", "not_linked")
        self.reason = kw.get("reason", "ga4_not_connected")

    async def event_stats(self):
        if self.stats is None:
            raise GoogleReadError(self.reason)
        return self.stats

    async def key_events(self):
        if self.key is None:
            raise GoogleReadError(self.reason)
        return self.key

    async def ads_links_count(self):
        if self.ads is None:
            raise GoogleReadError(self.reason)
        return self.ads

    async def measurement_id(self):
        raise GoogleReadError(self.reason)

    async def sitemaps_count(self):
        if self.sitemaps is None:
            raise GoogleReadError("gsc_not_connected")
        return self.sitemaps


class _Verifier:
    def __init__(self, error: str | None = None) -> None:
        self.calls = 0
        self.error = error

    async def __call__(self, url: str) -> GtmHeadlessResult:
        self.calls += 1
        return GtmHeadlessResult(
            gtm_js_loaded=self.error is None,
            containers_initialised=("GTM-AAAA111",) if self.error is None else (),
            datalayer_present=True,
            gtm_events=("view_item",),
            requests_before_consent=True,
            csp_console_errors=(),
            findings=(),
            checked_at=datetime.now(UTC),
            error=self.error,
            ga4_measurement_ids=("G-ABC123XYZ",),
            ads_requests=0,
            consent_default_seen=False,
        )


async def _site(db_session: AsyncSession, make_user, domain: str) -> Website:
    user = await make_user(sub=f"svc-{domain}")
    workspace_id = await owner_workspace_id(db_session, user)
    site = Website(
        workspace_id=workspace_id,
        domain=domain,
        display_name=domain,
        detected_stack=StackKind.GENERIC,
        ssl_status="valid",
    )
    db_session.add(site)
    await db_session.flush()
    return site


def _item(view: dict, item_id: str) -> dict:
    return next(item for item in view["items"] if item["id"] == item_id)


async def test_refresh_persists_states_and_detects_the_site_type(
    db_session: AsyncSession, make_user
) -> None:
    site = await _site(db_session, make_user, "svc-shop.test")
    await refresh_plan(
        db_session,
        site,
        fetcher=_Fetcher(),
        reader=_Reader(),
        verifier=_Verifier(),
        run_headless=False,
    )
    view = await build_plan_view(db_session, site)

    assert view["profile"]["effective_types"] == ["ecommerce"]
    assert view["profile"]["needs_confirmation"] is True
    assert _item(view, "gtm_installed")["state"] == "on_page"
    assert _item(view, "gtm_installed")["done"] is True
    assert _item(view, "event_purchase")["state"] == "unverifiable"
    assert _item(view, "event_purchase")["reason"] == "ga4_not_connected"
    assert _item(view, "event_generate_lead")["state"] == "not_applicable"
    assert _item(view, "robots_txt")["state"] == "on_page"
    assert _item(view, "tls_valid")["state"] == "on_page"
    assert view["last_checked_at"] is not None
    assert view["overall_total"] > 0
    assert view["ga4_connected"] is False
    assert view["gsc_linked"] is False
    assert view["google_connection"] == "none"
    # La couche publicité reste masquée tant que l'utilisateur n'a rien indiqué.
    assert _item(view, "ads_ga4_link")["state"] == "not_applicable"


async def test_ga4_data_upgrades_events_to_received_and_computes_progress(
    db_session: AsyncSession, make_user
) -> None:
    site = await _site(db_session, make_user, "svc-received.test")
    db_session.add(
        WebsiteProfile(website_id=site.id, detected_types=[], params={"uses_google_ads": True})
    )
    await db_session.flush()
    reader = _Reader(
        stats={
            "page_view": {"count": 400.0},
            "purchase": {"count": 5.0, "revenue": 250.0, "value": 0.0},
        },
        key=[{"eventName": "purchase"}],
        ads=0,
        sitemaps=1,
        gsc_state="linked",
    )
    await refresh_plan(
        db_session, site, fetcher=_Fetcher(), reader=reader, verifier=_Verifier(), run_headless=False
    )
    view = await build_plan_view(db_session, site)

    assert _item(view, "event_purchase")["state"] == "received"
    assert _item(view, "event_purchase")["evidence"]["ga4_count_30d"] == 5
    assert _item(view, "purchase_params")["state"] == "received"
    assert _item(view, "key_events_marked")["state"] == "received"
    assert _item(view, "ads_ga4_link")["state"] == "missing"
    assert _item(view, "gsc_property_linked")["state"] == "received"
    assert _item(view, "gsc_sitemaps")["state"] == "received"
    assert _item(view, "ga4_tag")["state"] == "received"
    layers = {layer["layer"]: layer for layer in view["layers"]}
    assert layers["seo"]["done"] >= 3
    assert view["overall_percent"] == round(100 * view["overall_done"] / view["overall_total"])
    assert view["ga4_connected"] is False  # aucune liaison GA4 en base dans ce test


async def test_confirmed_types_prevail_and_change_applicability(
    db_session: AsyncSession, make_user
) -> None:
    site = await _site(db_session, make_user, "svc-confirm.test")
    await refresh_plan(
        db_session, site, fetcher=_Fetcher(), reader=_Reader(), verifier=_Verifier(), run_headless=False
    )
    profile = await db_session.get(WebsiteProfile, site.id)
    profile.confirmed_types = ["lead_gen"]
    await refresh_plan(
        db_session, site, fetcher=_Fetcher(), reader=_Reader(), verifier=_Verifier(), run_headless=False
    )
    view = await build_plan_view(db_session, site)
    assert view["profile"]["effective_types"] == ["lead_gen"]
    assert view["profile"]["needs_confirmation"] is False
    assert _item(view, "event_purchase")["state"] == "not_applicable"
    assert _item(view, "event_generate_lead")["state"] != "not_applicable"


async def test_ads_layer_is_hidden_until_the_user_says_they_run_ads(
    db_session: AsyncSession, make_user
) -> None:
    site = await _site(db_session, make_user, "svc-ads.test")
    await refresh_plan(
        db_session, site, fetcher=_Fetcher(), reader=_Reader(), verifier=_Verifier(), run_headless=False
    )
    view = await build_plan_view(db_session, site)
    assert _item(view, "ads_ga4_link")["state"] == "not_applicable"
    assert _item(view, "ads_auto_tagging")["state"] == "not_applicable"

    profile = await db_session.get(WebsiteProfile, site.id)
    profile.params = {"uses_google_ads": True}
    await refresh_plan(
        db_session, site, fetcher=_Fetcher(), reader=_Reader(), verifier=_Verifier(), run_headless=False
    )
    view = await build_plan_view(db_session, site)
    assert _item(view, "ads_ga4_link")["state"] != "not_applicable"
    assert _item(view, "ads_auto_tagging")["state"] == "unverifiable"

    profile.params = {"uses_google_ads": False}
    await refresh_plan(
        db_session, site, fetcher=_Fetcher(), reader=_Reader(), verifier=_Verifier(), run_headless=False
    )
    view = await build_plan_view(db_session, site)
    assert _item(view, "ads_ga4_link")["state"] == "not_applicable"


async def test_unreachable_site_makes_page_items_unverifiable(
    db_session: AsyncSession, make_user
) -> None:
    site = await _site(db_session, make_user, "svc-down.test")
    await refresh_plan(
        db_session,
        site,
        fetcher=_Fetcher(html=None),
        reader=_Reader(),
        verifier=_Verifier(),
        run_headless=False,
    )
    view = await build_plan_view(db_session, site)
    gtm = _item(view, "gtm_installed")
    assert gtm["state"] == "unverifiable" and gtm["reason"] == "fetch_error"
    assert _item(view, "tls_valid")["state"] == "on_page"  # ne dépend pas de la page


async def test_headless_runs_once_then_cooldown_and_result_is_reused(
    db_session: AsyncSession, make_user
) -> None:
    site = await _site(db_session, make_user, "svc-headless.test")
    verifier = _Verifier()
    now = datetime(2026, 9, 24, 12, 0, tzinfo=UTC)
    first = await refresh_plan(
        db_session,
        site,
        fetcher=_Fetcher(),
        reader=_Reader(),
        verifier=verifier,
        run_headless=True,
        now=now,
    )
    assert first.headless_ran is True and verifier.calls == 1
    view = await build_plan_view(db_session, site)
    assert _item(view, "ga4_tag")["state"] == "on_page"  # vu par le navigateur

    second = await refresh_plan(
        db_session,
        site,
        fetcher=_Fetcher(),
        reader=_Reader(),
        verifier=verifier,
        run_headless=True,
        now=now + timedelta(minutes=2),
    )
    assert second.headless_skipped is True and verifier.calls == 1

    third = await refresh_plan(
        db_session,
        site,
        fetcher=_Fetcher(),
        reader=_Reader(),
        verifier=verifier,
        run_headless=True,
        now=now + COOLDOWN + timedelta(seconds=1),
    )
    assert third.headless_ran is True and verifier.calls == 2

    # Sans headless, le dernier résultat conservé est réutilisé (pas de « clignotement »).
    await refresh_plan(
        db_session,
        site,
        fetcher=_Fetcher(),
        reader=_Reader(),
        verifier=verifier,
        run_headless=False,
        now=now + timedelta(hours=1),
    )
    view = await build_plan_view(db_session, site)
    assert _item(view, "ga4_tag")["state"] == "on_page"


async def test_headless_error_keeps_the_previous_result(
    db_session: AsyncSession, make_user
) -> None:
    site = await _site(db_session, make_user, "svc-headless-err.test")
    result = await refresh_plan(
        db_session,
        site,
        fetcher=_Fetcher(),
        reader=_Reader(),
        verifier=_Verifier(error="TimeoutError: boom"),
        run_headless=True,
    )
    assert result.headless_ran is False
    assert result.headless_error == "TimeoutError: boom"
    profile = await db_session.get(WebsiteProfile, site.id)
    assert profile.headless_result is None
    view = await build_plan_view(db_session, site)
    assert view["headless_checked_at"] is None


async def test_a_good_headless_result_survives_a_later_failed_run(
    db_session: AsyncSession, make_user
) -> None:
    site = await _site(db_session, make_user, "svc-headless-keep.test")
    now = datetime(2026, 9, 24, 12, 0, tzinfo=UTC)
    await refresh_plan(
        db_session, site, fetcher=_Fetcher(), reader=_Reader(), verifier=_Verifier(),
        run_headless=True, now=now,
    )
    profile = await db_session.get(WebsiteProfile, site.id)
    kept = dict(profile.headless_result)
    kept_at = profile.headless_checked_at
    assert kept["ga4_ids"] == ["G-ABC123XYZ"]

    later = now + COOLDOWN + timedelta(minutes=1)
    result = await refresh_plan(
        db_session, site, fetcher=_Fetcher(), reader=_Reader(),
        verifier=_Verifier(error="TimeoutError: boom"), run_headless=True, now=later,
    )
    assert result.headless_ran is False and result.headless_error == "TimeoutError: boom"
    assert profile.headless_result == kept
    assert profile.headless_checked_at == kept_at
    view = await build_plan_view(db_session, site)
    assert view["headless_checked_at"] == kept_at
    assert _item(view, "ga4_tag")["state"] == "on_page"  # la preuve précédente reste utilisée


async def test_dismissed_and_manual_done_survive_a_refresh(
    db_session: AsyncSession, make_user
) -> None:
    site = await _site(db_session, make_user, "svc-persist.test")
    await refresh_plan(
        db_session, site, fetcher=_Fetcher(), reader=_Reader(), verifier=_Verifier(), run_headless=False
    )
    rows = {
        row.item_id: row
        for row in (
            await db_session.execute(
                select(MeasurementItemStatus).where(MeasurementItemStatus.website_id == site.id)
            )
        ).scalars()
    }
    rows["robots_txt"].dismissed_at = datetime.now(UTC)
    rows["ads_auto_tagging"].evidence = {"manual_done": True}
    profile = await db_session.get(WebsiteProfile, site.id)
    profile.params = {"uses_google_ads": True}  # la couche Ads doit être visible
    await refresh_plan(
        db_session, site, fetcher=_Fetcher(), reader=_Reader(), verifier=_Verifier(), run_headless=False
    )
    view = await build_plan_view(db_session, site)
    assert _item(view, "robots_txt")["state"] == "dismissed"
    assert _item(view, "ads_auto_tagging")["state"] == "on_page"
    assert _item(view, "ads_auto_tagging")["done"] is True


async def test_view_before_any_refresh_is_all_unknown(
    db_session: AsyncSession, make_user
) -> None:
    site = await _site(db_session, make_user, "svc-empty.test")
    view = await build_plan_view(db_session, site)
    assert view["last_checked_at"] is None
    assert view["profile"]["effective_types"] == ["other"]
    assert all(item["state"] == "unknown" for item in view["items"])
    assert view["overall_done"] == 0
    assert view["next_actions"] == []  # rien à recommander tant que rien n'est vérifié


async def test_view_orders_by_layer_then_weight_and_ships_snippets(
    db_session: AsyncSession, make_user
) -> None:
    site = await _site(db_session, make_user, "svc-order.test")
    await refresh_plan(
        db_session, site, fetcher=_Fetcher(), reader=_Reader(), verifier=_Verifier(), run_headless=False
    )
    view = await build_plan_view(db_session, site)
    layers = [item["layer"] for item in view["items"]]
    order = ["foundations", "events", "conversions", "ads", "seo"]
    assert layers == sorted(layers, key=order.index)
    foundations = [i["weight"] for i in view["items"] if i["layer"] == "foundations"]
    assert foundations == sorted(foundations, reverse=True)
    purchase = _item(view, "event_purchase")
    assert purchase["snippet"] is not None and "purchase" in purchase["snippet"]["code"]
    assert _item(view, "gtm_installed")["snippet"] is None


async def test_next_actions_lead_with_the_missing_items_that_matter_most(
    db_session: AsyncSession, make_user
) -> None:
    site = await _site(db_session, make_user, "svc-next.test")
    await refresh_plan(
        db_session,
        site,
        fetcher=_Fetcher(html="<html><head></head><body>Bonjour</body></html>"),
        reader=_Reader(),
        verifier=_Verifier(),
        run_headless=False,
    )
    view = await build_plan_view(db_session, site)
    actions = view["next_actions"]
    assert len(actions) == 3
    assert actions[0] == "gtm_installed"  # manquant, poids 100, gain rapide
    by_id = {item["id"]: item for item in view["items"]}
    for item_id in actions:
        assert by_id[item_id]["done"] is False
        assert by_id[item_id]["state"] not in ("not_applicable", "dismissed")


async def test_next_actions_skip_what_is_already_done(
    db_session: AsyncSession, make_user
) -> None:
    site = await _site(db_session, make_user, "svc-next-done.test")
    await refresh_plan(
        db_session, site, fetcher=_Fetcher(), reader=_Reader(), verifier=_Verifier(), run_headless=False
    )
    view = await build_plan_view(db_session, site)
    assert "gtm_installed" not in view["next_actions"]  # GTM est déjà en place


async def test_state_changes_are_recorded_once_and_in_order(
    db_session: AsyncSession, make_user
) -> None:
    site = await _site(db_session, make_user, "svc-events.test")
    t0 = datetime(2026, 9, 24, 9, 0, tzinfo=UTC)
    bare = _Fetcher(html="<html><head></head><body>Bonjour</body></html>")

    async def events(item_id: str) -> list[tuple[str | None, str]]:
        rows = (
            await db_session.execute(
                select(MeasurementItemEvent)
                .where(
                    MeasurementItemEvent.website_id == site.id,
                    MeasurementItemEvent.item_id == item_id,
                )
                .order_by(MeasurementItemEvent.at)
            )
        ).scalars().all()
        return [(row.from_state, row.to_state) for row in rows]

    await refresh_plan(
        db_session, site, fetcher=bare, reader=_Reader(), verifier=_Verifier(),
        run_headless=False, now=t0,
    )
    assert await events("gtm_installed") == [(None, "missing")]
    total = len((await db_session.execute(select(MeasurementItemEvent))).scalars().all())

    # Même résultat : aucune nouvelle ligne.
    await refresh_plan(
        db_session, site, fetcher=bare, reader=_Reader(), verifier=_Verifier(),
        run_headless=False, now=t0 + timedelta(minutes=10),
    )
    assert len((await db_session.execute(select(MeasurementItemEvent))).scalars().all()) == total

    # GTM apparaît : une transition « missing -> on_page ».
    await refresh_plan(
        db_session, site, fetcher=_Fetcher(), reader=_Reader(), verifier=_Verifier(),
        run_headless=False, now=t0 + timedelta(hours=1),
    )
    assert await events("gtm_installed") == [(None, "missing"), ("missing", "on_page")]


async def test_invalid_confirmed_types_are_ignored(db_session: AsyncSession, make_user) -> None:
    site = await _site(db_session, make_user, "svc-badtypes.test")
    await refresh_plan(
        db_session, site, fetcher=_Fetcher(), reader=_Reader(), verifier=_Verifier(), run_headless=False
    )
    profile = await db_session.get(WebsiteProfile, site.id)
    profile.confirmed_types = ["lead_gen", "lead_gen", "bogus"]
    view = await build_plan_view(db_session, site)
    assert view["profile"]["confirmed_types"] == ["lead_gen"]
    assert view["profile"]["effective_types"] == ["lead_gen"]

    profile.confirmed_types = ["bogus"]
    view = await build_plan_view(db_session, site)
    assert view["profile"]["confirmed_types"] is None
    assert view["profile"]["needs_confirmation"] is True


async def test_stale_headless_result_is_discarded(db_session: AsyncSession, make_user) -> None:
    site = await _site(db_session, make_user, "svc-stale.test")
    now = datetime(2026, 9, 24, 12, 0, tzinfo=UTC)
    await refresh_plan(
        db_session, site, fetcher=_Fetcher(), reader=_Reader(), verifier=_Verifier(),
        run_headless=True, now=now,
    )
    await refresh_plan(
        db_session, site, fetcher=_Fetcher(), reader=_Reader(), verifier=_Verifier(),
        run_headless=False, now=now + timedelta(days=2),
    )
    view = await build_plan_view(db_session, site)
    assert _item(view, "ga4_tag")["state"] == "unverifiable"  # plus aucune preuve fraîche


async def test_fetch_page_safe_never_raises(monkeypatch) -> None:
    async def boom(url: str, *, allow_insecure: bool = False):
        raise httpx.ConnectError("down")

    monkeypatch.setattr(fetch_module, "fetch_page", boom)
    assert await fetch_module.fetch_page_safe("https://x.test") is None


@pytest.mark.parametrize("reason", ["api_error", "network"])
async def test_google_read_failures_are_unverifiable_never_missing(
    db_session: AsyncSession, make_user, reason: str
) -> None:
    site = await _site(db_session, make_user, f"svc-{reason}.test")
    db_session.add(
        WebsiteProfile(website_id=site.id, detected_types=[], params={"uses_google_ads": True})
    )
    await db_session.flush()
    await refresh_plan(
        db_session, site, fetcher=_Fetcher(), reader=_Reader(reason=reason),
        verifier=_Verifier(), run_headless=False,
    )
    view = await build_plan_view(db_session, site)
    for item_id in ("event_purchase", "purchase_params", "key_events_marked", "ads_ga4_link"):
        item = _item(view, item_id)
        assert item["state"] == "unverifiable", item_id
        assert item["reason"] == reason, item_id
        assert item["done"] is False


@pytest.mark.parametrize(
    ("kwargs", "reason"),
    [
        ({"page_status": 503}, "http_error"),
        ({"page_ctype": "application/pdf"}, "non_html"),
    ],
)
async def test_unusable_page_makes_page_items_unverifiable(
    db_session: AsyncSession, make_user, kwargs: dict, reason: str
) -> None:
    site = await _site(db_session, make_user, f"svc-{reason}.test")
    await refresh_plan(
        db_session, site, fetcher=_Fetcher(**kwargs), reader=_Reader(),
        verifier=_Verifier(), run_headless=False,
    )
    view = await build_plan_view(db_session, site)
    gtm = _item(view, "gtm_installed")
    assert gtm["state"] == "unverifiable" and gtm["reason"] == reason
    assert view["profile"]["effective_types"] == ["other"]  # aucune détection sans HTML


@pytest.mark.parametrize(
    ("robots_status", "robots_ctype", "state", "reason"),
    [
        (404, "text/plain", "missing", None),
        (410, "text/plain", "missing", None),
        (503, "text/plain", "unverifiable", "robots_unreadable"),
        (403, "text/plain", "unverifiable", "robots_unreadable"),
        (200, "text/html; charset=utf-8", "unverifiable", "robots_unreadable"),
        (200, "text/plain", "on_page", None),
        (200, "", "on_page", None),
    ],
)
async def test_robots_txt_is_only_judged_on_clear_evidence(
    db_session: AsyncSession,
    make_user,
    robots_status: int,
    robots_ctype: str,
    state: str,
    reason: str | None,
) -> None:
    site = await _site(db_session, make_user, f"svc-robots-{robots_status}-{len(robots_ctype)}.test")
    fetcher = _Fetcher(robots_status=robots_status, robots_ctype=robots_ctype)
    await refresh_plan(
        db_session, site, fetcher=fetcher, reader=_Reader(), verifier=_Verifier(),
        run_headless=False,
    )
    item = _item(await build_plan_view(db_session, site), "robots_txt")
    assert item["state"] == state
    assert item["reason"] == reason


async def test_google_connection_and_links_are_reflected_in_the_view(
    db_session: AsyncSession, make_user
) -> None:
    site = await _site(db_session, make_user, "svc-google.test")
    connection = GoogleConnection(
        workspace_id=site.workspace_id,
        google_account_email="owner@example.com",
        google_sub="google-sub-1",
        granted_scopes=[],
        refresh_token_encrypted=b"x",
        encryption_key_version=1,
        status=ConnectionStatus.ACTIVE,
    )
    db_session.add(connection)
    await db_session.flush()
    for resource_type, resource_id in (
        (ResourceType.GA4_PROPERTY, "properties/1"),
        (ResourceType.GSC_SITE, "sc-domain:svc-google.test"),
    ):
        db_session.add(
            WebsiteGoogleLink(
                website_id=site.id,
                google_connection_id=connection.id,
                resource_type=resource_type,
                resource_id=resource_id,
            )
        )
    await db_session.flush()
    view = await build_plan_view(db_session, site)
    assert view["google_connection"] == "active"
    assert view["ga4_connected"] is True and view["gsc_linked"] is True

    connection.status = ConnectionStatus.NEEDS_REAUTH
    await db_session.flush()
    view = await build_plan_view(db_session, site)
    assert view["google_connection"] == "needs_reauth"
    assert view["ga4_connected"] is True and view["gsc_linked"] is True


async def test_next_actions_break_ties_in_catalog_order(
    db_session: AsyncSession, make_user
) -> None:
    site = await _site(db_session, make_user, "svc-ties.test")
    await refresh_plan(
        db_session, site, fetcher=_Fetcher(html="<html><head></head><body>x</body></html>"),
        reader=_Reader(), verifier=_Verifier(), run_headless=False,
    )
    view = await build_plan_view(db_session, site)
    by_id = {item["id"]: item for item in view["items"]}
    catalog_pos = {item.id: index for index, item in enumerate(ITEMS)}
    for first, second in zip(view["next_actions"], view["next_actions"][1:], strict=False):
        a, b = by_id[first], by_id[second]
        if (a["weight"], a["quick_win"], a["layer"]) == (b["weight"], b["quick_win"], b["layer"]):
            assert catalog_pos[first] < catalog_pos[second]
    # Deux calculs successifs donnent le même classement.
    assert (await build_plan_view(db_session, site))["next_actions"] == view["next_actions"]


async def test_fetch_page_safe_swallows_invalid_urls(monkeypatch) -> None:
    async def boom(url: str, *, allow_insecure: bool = False):
        raise httpx.InvalidURL("bad url")

    monkeypatch.setattr(fetch_module, "fetch_page", boom)
    assert await fetch_module.fetch_page_safe("https://exa mple.test") is None


class _SlowFetcher(_Fetcher):
    """Force l'entrelacement des deux rafraîchissements (sans verrou, ils se chevauchent)."""

    async def __call__(self, url: str, *, allow_insecure: bool = False):
        await asyncio.sleep(0.05)
        return await super().__call__(url, allow_insecure=allow_insecure)


async def test_concurrent_refreshes_of_one_site_write_a_single_history(engine) -> None:
    maker = async_sessionmaker(bind=engine, expire_on_commit=False)
    async with maker() as setup:
        user = User(email="race@example.com", google_sub="race-sub")
        setup.add(user)
        await setup.flush()
        workspace = Workspace(name="race", owner_user_id=user.id)
        setup.add(workspace)
        await setup.flush()
        site = Website(
            workspace_id=workspace.id,
            domain="svc-race.test",
            display_name="race",
            detected_stack=StackKind.GENERIC,
            ssl_status="valid",
        )
        setup.add(site)
        await setup.commit()
        site_id, workspace_id, user_id = site.id, workspace.id, user.id

    ready = asyncio.Barrier(2)  # les deux connexions sont ouvertes avant de commencer

    async def one_refresh() -> None:
        async with maker() as session:
            website = await session.get(Website, site_id)
            await ready.wait()
            await refresh_plan(
                session, website, fetcher=_SlowFetcher(), reader=_Reader(),
                verifier=_Verifier(), run_headless=False,
            )
            await session.commit()

    try:
        await asyncio.gather(one_refresh(), one_refresh())
        async with maker() as check:
            profiles = (
                await check.execute(
                    select(WebsiteProfile).where(WebsiteProfile.website_id == site_id)
                )
            ).scalars().all()
            events = (
                await check.execute(
                    select(MeasurementItemEvent.item_id).where(
                        MeasurementItemEvent.website_id == site_id
                    )
                )
            ).scalars().all()
            statuses = (
                await check.execute(
                    select(MeasurementItemStatus.item_id).where(
                        MeasurementItemStatus.website_id == site_id
                    )
                )
            ).scalars().all()
        assert len(profiles) == 1
        assert len(events) == len(set(events))  # une seule première observation par item
        assert len(statuses) == len(set(statuses)) > 0
    finally:
        async with maker() as cleanup:
            await cleanup.execute(delete(Website).where(Website.id == site_id))
            await cleanup.execute(delete(Workspace).where(Workspace.id == workspace_id))
            await cleanup.execute(delete(User).where(User.id == user_id))
            await cleanup.commit()
