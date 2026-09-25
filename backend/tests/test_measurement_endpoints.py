# backend/tests/test_measurement_endpoints.py
import asyncio
from datetime import UTC, datetime

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, func, select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.deps import (
    get_google_client,
    get_gtm_headless_verifier,
    get_measurement_reader_factory,
    get_page_fetcher,
    get_stream_hosts_fetcher,
)
from app.api.v1.endpoints import measurement as measurement_endpoints
from app.config import get_settings
from app.db.session import get_session
from app.main import app
from app.models.measurement_item_event import MeasurementItemEvent
from app.models.user import User
from app.models.website import Website
from app.models.website_profile import WebsiteProfile
from app.models.workspace import Workspace
from app.models.workspace_member import WorkspaceMember
from app.security.session import issue_session
from app.security.token_crypto import load_token_cipher
from app.services.connections import upsert_google_connection
from app.services.google_oauth.base import (
    DiscoveredResources,
    Ga4Property,
    GoogleTokenResponse,
    GoogleUserInfo,
    GscSite,
)
from app.services.gtm_headless import GtmHeadlessResult
from app.services.measurement.google_reader import GoogleReadError
from app.services.measurement.service import lock_site
from app.services.page_fetch import PageSnapshot
from tests.conftest import owner_workspace_id
from tests.measurement_fakes import FakeOAuth, fake_stream_hosts

_HTML = """<html><head><script>(function(w,d,s,l,i){})(window,document,'script','dataLayer','GTM-AAAA111');
</script><script src="https://www.googletagmanager.com/gtm.js?id=GTM-AAAA111"></script></head>
<body><a href="tel:+33400000000">Appeler</a><form action="/contact"></form>
<p>Demandez un devis gratuit</p></body></html>"""


class _Reader:
    gsc_state = "not_linked"

    async def event_stats(self):
        raise GoogleReadError("ga4_not_connected")

    async def key_events(self):
        raise GoogleReadError("ga4_not_connected")

    async def ads_links_count(self):
        raise GoogleReadError("ga4_not_connected")

    async def measurement_id(self):
        return "G-ABC123XYZ"

    async def sitemaps_count(self):
        raise GoogleReadError("gsc_not_connected")


async def _fetcher(url: str, *, allow_insecure: bool = False):
    ctype = "text/plain" if url.endswith("robots.txt") else "text/html"
    return PageSnapshot(
        url=url,
        final_url=url,
        status=200,
        html=_HTML,
        headers={"content-type": ctype},
        redirected=False,
        history=(),
    )


async def _verifier(url: str) -> GtmHeadlessResult:
    return GtmHeadlessResult(
        gtm_js_loaded=True,
        containers_initialised=("GTM-AAAA111",),
        datalayer_present=True,
        gtm_events=(),
        requests_before_consent=True,
        csp_console_errors=(),
        findings=(),
        checked_at=datetime.now(UTC),
        ga4_measurement_ids=("G-ABC123XYZ",),
    )


@pytest_asyncio.fixture
def measurement_overrides():
    async def _factory(session, website):
        return _Reader()

    app.dependency_overrides[get_page_fetcher] = lambda: _fetcher
    app.dependency_overrides[get_measurement_reader_factory] = lambda: _factory
    app.dependency_overrides[get_gtm_headless_verifier] = lambda: _verifier
    yield
    for dep in (get_page_fetcher, get_measurement_reader_factory, get_gtm_headless_verifier):
        app.dependency_overrides.pop(dep, None)


async def _site(db_session: AsyncSession, user: User, domain: str) -> Website:
    workspace_id = await owner_workspace_id(db_session, user)
    site = Website(workspace_id=workspace_id, domain=domain, display_name=domain, ssl_status="valid")
    db_session.add(site)
    await db_session.flush()
    return site


def _url(site: Website, suffix: str = "") -> str:
    return f"/api/v1/websites/{site.id}/measurement-plan{suffix}"


async def test_endpoints_require_authentication(db_client: AsyncClient) -> None:
    fake = "00000000-0000-0000-0000-000000000000"
    assert (await db_client.get(f"/api/v1/websites/{fake}/measurement-plan")).status_code == 401


async def test_get_before_refresh_then_refresh(
    authed_client: tuple[AsyncClient, User], db_session: AsyncSession, measurement_overrides
) -> None:
    client, user = authed_client
    site = await _site(db_session, user, "mpe-refresh.test")

    empty = (await client.get(_url(site))).json()
    assert empty["last_checked_at"] is None
    assert all(item["state"] == "unknown" for item in empty["items"])

    resp = await client.post(_url(site, "/refresh"))
    assert resp.status_code == 200, resp.text
    plan = resp.json()
    assert plan["profile"]["effective_types"] == ["lead_gen"]
    assert plan["profile"]["needs_confirmation"] is True
    by_id = {item["id"]: item for item in plan["items"]}
    assert by_id["gtm_installed"]["state"] == "on_page"
    assert by_id["event_generate_lead"]["state"] == "unverifiable"
    assert by_id["event_generate_lead"]["reason"] == "ga4_not_connected"
    assert plan["headless_skipped"] is False
    assert {"layer", "total", "done"} <= set(plan["layers"][0])
    assert plan["ga4_connected"] is False and plan["gsc_linked"] is False
    assert plan["google_connection"] == "none"
    assert 1 <= len(plan["next_actions"]) <= 3
    assert "gtm_installed" not in plan["next_actions"]  # déjà en place sur la page de test


async def test_refresh_with_headless_then_cooldown(
    authed_client: tuple[AsyncClient, User], db_session: AsyncSession, measurement_overrides
) -> None:
    client, user = authed_client
    site = await _site(db_session, user, "mpe-headless.test")

    first = (await client.post(_url(site, "/refresh"), params={"headless": "true"})).json()
    assert first["headless_skipped"] is False
    by_id = {item["id"]: item for item in first["items"]}
    assert by_id["ga4_tag"]["state"] == "on_page"

    second = (await client.post(_url(site, "/refresh"), params={"headless": "true"})).json()
    assert second["headless_skipped"] is True


async def test_owner_can_confirm_types_and_set_ads_params(
    authed_client: tuple[AsyncClient, User], db_session: AsyncSession, measurement_overrides
) -> None:
    client, user = authed_client
    site = await _site(db_session, user, "mpe-profile.test")

    resp = await client.patch(
        _url(site, "/profile"),
        json={
            "confirmed_types": ["ecommerce", "content"],
            "ads_conversion_id": "AW-123456789",
            "ads_conversion_label": "AbCdEfGhIjK",
            "uses_google_ads": True,
            "ga4_measurement_id": "G-ABC123XYZ",
        },
    )
    assert resp.status_code == 200, resp.text
    profile = resp.json()["profile"]
    assert profile["confirmed_types"] == ["ecommerce", "content"]
    assert profile["needs_confirmation"] is False
    assert profile["params"]["ads_conversion_id"] == "AW-123456789"
    assert profile["params"]["uses_google_ads"] is True

    cleared = await client.patch(_url(site, "/profile"), json={"ads_conversion_id": None})
    assert cleared.json()["profile"]["params"]["ads_conversion_id"] is None
    assert cleared.json()["profile"]["params"]["ads_conversion_label"] == "AbCdEfGhIjK"


async def test_profile_validation(
    authed_client: tuple[AsyncClient, User], db_session: AsyncSession, measurement_overrides
) -> None:
    client, user = authed_client
    site = await _site(db_session, user, "mpe-validate.test")
    for body in (
        {"confirmed_types": ["unknown_type"]},
        {"ads_conversion_id": "123"},
        {"ads_conversion_label": "x"},
        {"ga4_measurement_id": "UA-1234"},
    ):
        assert (await client.patch(_url(site, "/profile"), json=body)).status_code == 422, body


async def test_non_owner_member_can_read_but_not_edit(
    authed_client: tuple[AsyncClient, User], db_session: AsyncSession, make_user, measurement_overrides
) -> None:
    client, user = authed_client
    other_owner = await make_user(sub="mpe-other-owner")
    other_ws = await owner_workspace_id(db_session, other_owner)
    site = Website(workspace_id=other_ws, domain="mpe-shared.test", display_name="Shared")
    db_session.add(site)
    db_session.add(WorkspaceMember(workspace_id=other_ws, user_id=user.id, role="member"))
    await db_session.flush()

    assert (await client.get(_url(site))).status_code == 200
    assert (await client.post(_url(site, "/refresh"))).status_code == 200
    assert (
        await client.patch(_url(site, "/profile"), json={"confirmed_types": ["saas"]})
    ).status_code == 403
    assert (
        await client.patch(_url(site, "/items/robots_txt"), json={"dismissed": True})
    ).status_code == 403


async def test_stranger_gets_404(
    authed_client: tuple[AsyncClient, User], db_session: AsyncSession, make_user, measurement_overrides
) -> None:
    client, _ = authed_client
    stranger = await make_user(sub="mpe-stranger")
    site = await _site(db_session, stranger, "mpe-private.test")
    assert (await client.get(_url(site))).status_code == 404


async def test_dismiss_and_manual_done(
    authed_client: tuple[AsyncClient, User], db_session: AsyncSession, measurement_overrides
) -> None:
    client, user = authed_client
    site = await _site(db_session, user, "mpe-items.test")
    await client.patch(_url(site, "/profile"), json={"uses_google_ads": True})
    await client.post(_url(site, "/refresh"))

    dismissed = await client.patch(_url(site, "/items/robots_txt"), json={"dismissed": True})
    assert dismissed.status_code == 200
    by_id = {i["id"]: i for i in dismissed.json()["items"]}
    assert by_id["robots_txt"]["state"] == "dismissed"
    history = (
        await db_session.execute(
            select(MeasurementItemEvent.from_state, MeasurementItemEvent.to_state).where(
                MeasurementItemEvent.website_id == site.id,
                MeasurementItemEvent.item_id == "robots_txt",
            )
        )
    ).all()
    assert ("on_page", "dismissed") in [tuple(row) for row in history]

    restored = await client.patch(_url(site, "/items/robots_txt"), json={"dismissed": False})
    assert {i["id"]: i for i in restored.json()["items"]}["robots_txt"]["state"] == "unknown"
    refreshed = (await client.post(_url(site, "/refresh"))).json()
    assert {i["id"]: i for i in refreshed["items"]}["robots_txt"]["state"] == "on_page"

    done = await client.patch(_url(site, "/items/ads_auto_tagging"), json={"manual_done": True})
    item = {i["id"]: i for i in done.json()["items"]}["ads_auto_tagging"]
    assert item["state"] == "on_page" and item["done"] is True
    after = (await client.post(_url(site, "/refresh"))).json()
    assert {i["id"]: i for i in after["items"]}["ads_auto_tagging"]["done"] is True

    assert (
        await client.patch(_url(site, "/items/gtm_installed"), json={"manual_done": True})
    ).status_code == 400
    assert (
        await client.patch(_url(site, "/items/does_not_exist"), json={"dismissed": True})
    ).status_code == 404


async def test_gtm_container_endpoint(
    authed_client: tuple[AsyncClient, User], db_session: AsyncSession, measurement_overrides
) -> None:
    client, user = authed_client
    site = await _site(db_session, user, "mpe-container.test")

    resp = await client.post(
        _url(site, "/gtm-container"),
        json={"item_ids": ["ga4_tag", "event_generate_lead", "event_click_to_call"]},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["filename"] == "gtm-plan-mpe-container.test.json"
    tags = [t["name"] for t in body["container"]["containerVersion"]["tag"]]
    assert "GA4 - generate_lead" in tags and "GA4 - click_to_call" in tags
    config = next(
        t for t in body["container"]["containerVersion"]["tag"] if t["name"] == "GA4 Configuration"
    )
    assert config["parameter"][0]["value"] == "G-ABC123XYZ"  # lu depuis GA4 (lecteur factice)
    assert body["warnings"] == []

    bad = await client.post(_url(site, "/gtm-container"), json={"item_ids": ["nope"]})
    assert bad.status_code == 400
    assert body["needs_site_code"] == ["event_generate_lead"]  # le clic tel: se détecte seul


async def test_gtm_container_starter_pack_follows_the_detected_type(
    authed_client: tuple[AsyncClient, User], db_session: AsyncSession, measurement_overrides
) -> None:
    client, user = authed_client
    site = await _site(db_session, user, "mpe-starter.test")
    await client.post(_url(site, "/refresh"))  # détecte « lead_gen » sur la page de test

    resp = await client.post(_url(site, "/gtm-container"), json={"pack": "starter"})
    assert resp.status_code == 200, resp.text
    tags = [t["name"] for t in resp.json()["container"]["containerVersion"]["tag"]]
    assert "GA4 Configuration" in tags
    assert "GA4 - generate_lead" in tags and "GA4 - click_to_call" in tags
    assert "GA4 - purchase" not in tags
    assert set(resp.json()["needs_site_code"]) == {"event_generate_lead"}

    # Exactement un des deux : la liste explicite OU le pack.
    both = await client.post(
        _url(site, "/gtm-container"), json={"pack": "starter", "item_ids": ["ga4_tag"]}
    )
    neither = await client.post(_url(site, "/gtm-container"), json={})
    assert both.status_code == 422 and neither.status_code == 422


async def test_refresh_is_rate_limited_per_user(
    authed_client: tuple[AsyncClient, User], db_session: AsyncSession, measurement_overrides
) -> None:
    client, user = authed_client
    site = await _site(db_session, user, "mpe-limit.test")
    codes = [(await client.post(_url(site, "/refresh"))).status_code for _ in range(11)]
    assert codes[:10] == [200] * 10
    assert codes[10] == 429


async def test_profile_patch_refreshes_states_and_dedupes_types(
    authed_client: tuple[AsyncClient, User], db_session: AsyncSession, measurement_overrides
) -> None:
    client, user = authed_client
    site = await _site(db_session, user, "mpe-follow.test")
    await client.post(_url(site, "/refresh"))

    before = (await client.get(_url(site))).json()
    ads_before = {i["id"]: i["state"] for i in before["items"] if i["layer"] == "ads"}
    assert ads_before and set(ads_before.values()) == {"not_applicable"}

    resp = await client.patch(
        _url(site, "/profile"),
        json={"uses_google_ads": True, "confirmed_types": ["saas", "saas", "content"]},
    )
    assert resp.status_code == 200, resp.text
    plan = resp.json()
    assert plan["profile"]["confirmed_types"] == ["saas", "content"]
    assert plan["profile"]["effective_types"] == ["saas", "content"]
    # Les états ont suivi sans relance manuelle : la couche Ads n'est plus « non concernée ».
    ads_after = {i["id"]: i["state"] for i in plan["items"] if i["layer"] == "ads"}
    assert "not_applicable" not in set(ads_after.values())

    unknown = await client.patch(_url(site, "/profile"), json={"confirmed_types": ["blog"]})
    assert unknown.status_code == 422
    assert "type de site inconnu" in unknown.text


async def test_headless_checked_at_is_exposed(
    authed_client: tuple[AsyncClient, User], db_session: AsyncSession, measurement_overrides
) -> None:
    client, user = authed_client
    site = await _site(db_session, user, "mpe-fresh.test")
    assert (await client.get(_url(site))).json()["headless_checked_at"] is None
    plan = (await client.post(_url(site, "/refresh"), params={"headless": "true"})).json()
    assert plan["headless_checked_at"] is not None


async def test_item_patch_body_validation_and_no_side_effects(
    authed_client: tuple[AsyncClient, User], db_session: AsyncSession, measurement_overrides
) -> None:
    client, user = authed_client
    site = await _site(db_session, user, "mpe-itemval.test")
    await client.post(_url(site, "/refresh"))

    assert (await client.patch(_url(site, "/items/robots_txt"), json={})).status_code == 422
    both = await client.patch(
        _url(site, "/items/ads_auto_tagging"), json={"dismissed": True, "manual_done": True}
    )
    assert both.status_code == 422

    async def _events(item_id: str) -> int:
        rows = await db_session.execute(
            select(MeasurementItemEvent.item_id).where(
                MeasurementItemEvent.website_id == site.id,
                MeasurementItemEvent.item_id == item_id,
            )
        )
        return len(rows.all())

    # « dismissed: false » sur un item qui n'est pas écarté : ni effet, ni événement.
    before = await _events("robots_txt")
    resp = await client.patch(_url(site, "/items/robots_txt"), json={"dismissed": False})
    assert resp.status_code == 200
    assert {i["id"]: i for i in resp.json()["items"]}["robots_txt"]["state"] == "on_page"
    assert await _events("robots_txt") == before

    # Item « non concerné » (couche Ads masquée) : le marquage est retenu mais l'item ne
    # réapparaît pas avant le prochain rafraîchissement.
    done = await client.patch(_url(site, "/items/ads_auto_tagging"), json={"manual_done": True})
    item = {i["id"]: i for i in done.json()["items"]}["ads_auto_tagging"]
    assert item["state"] == "not_applicable"
    assert item["evidence"] == {"manual_done": True}
    off = await client.patch(_url(site, "/items/ads_auto_tagging"), json={"dismissed": False})
    by_id = {i["id"]: i for i in off.json()["items"]}
    assert by_id["ads_auto_tagging"]["state"] == "not_applicable"


async def test_container_is_read_only_dedupes_and_rejects_empty_selection(
    authed_client: tuple[AsyncClient, User], db_session: AsyncSession, measurement_overrides
) -> None:
    client, user = authed_client
    site = await _site(db_session, user, "mpe-container-ro.test")

    resp = await client.post(
        _url(site, "/gtm-container"),
        json={"item_ids": ["ga4_tag", "ga4_tag", "event_generate_lead", "event_generate_lead"]},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["needs_site_code"] == ["event_generate_lead"]
    empty = await client.post(_url(site, "/gtm-container"), json={"item_ids": []})
    assert empty.status_code == 422
    # Aucune ligne de profil créée par la génération du conteneur.
    profiles = await db_session.scalar(
        select(func.count()).select_from(WebsiteProfile).where(WebsiteProfile.website_id == site.id)
    )
    assert profiles == 0


async def test_starter_pack_ignores_invalid_confirmed_types(
    authed_client: tuple[AsyncClient, User], db_session: AsyncSession, measurement_overrides
) -> None:
    client, user = authed_client
    clean = await _site(db_session, user, "mpe-pack-clean.test")
    dirty = await _site(db_session, user, "mpe-pack-dirty.test")
    db_session.add(
        WebsiteProfile(
            website_id=dirty.id, detected_types=[], params={}, confirmed_types=["bogus"]
        )
    )
    await db_session.flush()

    def _tags(resp) -> set[str]:
        return {t["name"] for t in resp.json()["container"]["containerVersion"]["tag"]}

    a = await client.post(_url(clean, "/gtm-container"), json={"pack": "starter"})
    b = await client.post(_url(dirty, "/gtm-container"), json={"pack": "starter"})
    assert a.status_code == b.status_code == 200
    assert _tags(a) == _tags(b)


async def test_profile_patch_survives_a_failing_followup_refresh(
    authed_client: tuple[AsyncClient, User],
    db_session: AsyncSession,
    measurement_overrides,
    monkeypatch,
) -> None:
    client, user = authed_client
    site = await _site(db_session, user, "mpe-followup-fail.test")

    async def _boom(*args, **kwargs):
        raise OperationalError("SELECT 1", {}, Exception("base indisponible"))

    monkeypatch.setattr(measurement_endpoints, "refresh_plan", _boom)
    resp = await client.patch(_url(site, "/profile"), json={"confirmed_types": ["saas"]})
    assert resp.status_code == 200, resp.text
    assert resp.json()["profile"]["confirmed_types"] == ["saas"]


async def test_profile_patch_counts_against_the_refresh_limit(
    authed_client: tuple[AsyncClient, User], db_session: AsyncSession, measurement_overrides
) -> None:
    client, user = authed_client
    site = await _site(db_session, user, "mpe-limit-profile.test")
    for _ in range(10):
        assert (await client.post(_url(site, "/refresh"))).status_code == 200
    blocked = await client.patch(_url(site, "/profile"), json={"confirmed_types": ["saas"]})
    assert blocked.status_code == 429
    # Un PATCH sans effet sur l'applicabilité (ID Ads seul) n'est pas concerné.
    ok = await client.patch(_url(site, "/profile"), json={"ads_conversion_id": "AW-123456789"})
    assert ok.status_code == 200


async def test_non_owner_member_can_build_the_container(
    authed_client: tuple[AsyncClient, User],
    db_session: AsyncSession,
    make_user,
    measurement_overrides,
) -> None:
    client, user = authed_client
    other_owner = await make_user(sub="mpe-container-owner")
    other_ws = await owner_workspace_id(db_session, other_owner)
    site = Website(workspace_id=other_ws, domain="mpe-member-container.test", display_name="M")
    db_session.add(site)
    db_session.add(WorkspaceMember(workspace_id=other_ws, user_id=user.id, role="member"))
    await db_session.flush()
    resp = await client.post(_url(site, "/gtm-container"), json={"item_ids": ["ga4_tag"]})
    assert resp.status_code == 200, resp.text


async def test_headless_refresh_is_limited_to_three_per_ten_minutes(
    authed_client: tuple[AsyncClient, User], db_session: AsyncSession, measurement_overrides
) -> None:
    client, user = authed_client
    site = await _site(db_session, user, "mpe-headless-limit.test")
    codes = [
        (await client.post(_url(site, "/refresh"), params={"headless": "true"})).status_code
        for _ in range(4)
    ]
    assert codes == [200, 200, 200, 429]


async def test_item_patch_waits_for_a_refresh_holding_the_site_lock(engine) -> None:
    """Un marquage manuel committé pendant un rafraîchissement serait écrasé : le PATCH
    doit attendre le verrou par site, puis s'appliquer sur l'état committé."""
    maker = async_sessionmaker(bind=engine, expire_on_commit=False)
    settings = get_settings()
    async with maker() as setup:
        user = User(email="lock10@example.com", google_sub="lock10-sub")
        setup.add(user)
        await setup.flush()
        workspace = Workspace(name="lock10", owner_user_id=user.id)
        setup.add(workspace)
        await setup.flush()
        setup.add(WorkspaceMember(workspace_id=workspace.id, user_id=user.id, role="owner"))
        site = Website(workspace_id=workspace.id, domain="mpe-lock.test", display_name="lock")
        setup.add(site)
        await setup.commit()
        site_id, workspace_id, user_id = site.id, workspace.id, user.id

    async def _session_override():
        async with maker() as request_session:
            yield request_session

    app.dependency_overrides[get_session] = _session_override
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            client.cookies.set(
                settings.session_cookie_name,
                issue_session(user_id, secret=settings.app_secret_key.get_secret_value()),
            )
            async with maker() as holder:
                await lock_site(holder, site_id)  # un rafraîchissement en cours
                task = asyncio.create_task(
                    client.patch(
                        f"/api/v1/websites/{site_id}/measurement-plan/items/ads_auto_tagging",
                        json={"manual_done": True},
                    )
                )
                # Preuve du blocage sans dépendre des durées (la connexion à la base peut
                # être lente) : un verrou consultatif en attente apparaît dans pg_locks.
                waiting = 0
                for _ in range(200):
                    assert not task.done(), "le PATCH ne doit pas passer outre le verrou du site"
                    waiting = await holder.scalar(
                        text(
                            "SELECT count(*) FROM pg_locks "
                            "WHERE locktype = 'advisory' AND NOT granted"
                        )
                    )
                    if waiting:
                        break
                    await asyncio.sleep(0.05)
                assert waiting, "le PATCH doit attendre le verrou du site"
                await holder.commit()
            resp = await asyncio.wait_for(task, timeout=10)
            assert resp.status_code == 200, resp.text
            item = {i["id"]: i for i in resp.json()["items"]}["ads_auto_tagging"]
            assert item["done"] is True
    finally:
        app.dependency_overrides.pop(get_session, None)
        async with maker() as cleanup:
            await cleanup.execute(delete(Website).where(Website.id == site_id))
            await cleanup.execute(delete(Workspace).where(Workspace.id == workspace_id))
            await cleanup.execute(delete(User).where(User.id == user_id))
            await cleanup.commit()


async def test_google_autolink_endpoint_links_and_returns_the_plan(
    authed_client: tuple[AsyncClient, User], db_session: AsyncSession, measurement_overrides
) -> None:
    client, user = authed_client
    site = await _site(db_session, user, "exemple.fr")
    await upsert_google_connection(
        db_session,
        workspace_id=site.workspace_id,
        userinfo=GoogleUserInfo(sub="g-endpoint", email="endpoint@gmail.com"),
        token=GoogleTokenResponse(
            access_token="a", expires_in=3600, scopes=("openid",), refresh_token="r"
        ),
        cipher=load_token_cipher(get_settings()),
    )
    resources = DiscoveredResources(
        ga4_properties=(Ga4Property("properties/1", "Exemple", "accounts/1", "Compte"),),
        gsc_sites=(GscSite("sc-domain:exemple.fr", "siteOwner"),),
    )
    app.dependency_overrides[get_google_client] = lambda: FakeOAuth(resources)
    app.dependency_overrides[get_stream_hosts_fetcher] = lambda: fake_stream_hosts(
        {"properties/1": {"exemple.fr"}}
    )
    try:
        resp = await client.post(_url(site, "/google-autolink"))
    finally:
        app.dependency_overrides.pop(get_google_client, None)
        app.dependency_overrides.pop(get_stream_hosts_fetcher, None)

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ga4"]["status"] == "linked"
    assert body["ga4"]["resource_id"] == "properties/1"
    assert body["ga4"]["candidates"] == []
    assert body["ga4"]["message"]
    assert body["gsc"]["status"] == "linked"
    # Le plan renvoyé a été rafraîchi après la liaison (états enregistrés).
    assert body["plan"]["last_checked_at"] is not None
    assert body["plan"]["ga4_connected"] is True and body["plan"]["gsc_linked"] is True
    assert body["plan"]["google_connection"] == "active"


async def test_google_autolink_without_connection_is_skipped(
    authed_client: tuple[AsyncClient, User], db_session: AsyncSession, measurement_overrides
) -> None:
    client, user = authed_client
    site = await _site(db_session, user, "sans-connexion.test")
    empty = DiscoveredResources(ga4_properties=(), gsc_sites=())
    app.dependency_overrides[get_google_client] = lambda: FakeOAuth(empty)
    app.dependency_overrides[get_stream_hosts_fetcher] = lambda: fake_stream_hosts({})
    try:
        resp = await client.post(_url(site, "/google-autolink"))
    finally:
        app.dependency_overrides.pop(get_google_client, None)
        app.dependency_overrides.pop(get_stream_hosts_fetcher, None)
    assert resp.status_code == 200
    assert resp.json()["ga4"]["status"] == "skipped"
    assert resp.json()["gsc"]["status"] == "skipped"
    assert resp.json()["plan"]["google_connection"] == "none"
