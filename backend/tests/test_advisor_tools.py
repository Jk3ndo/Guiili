from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
from sqlalchemy import select

from app.models.advisor import AdvisorThread, AdvisorToolCall
from app.models.audit_snapshot import AuditSnapshot
from app.models.enums import SnapshotSource, StackKind
from app.models.website import Website
from app.services.advisor.tools import ToolContext, _get_page_html, dispatch
from app.services.audit_probe import MockAuditProbe
from app.services.gtm_headless import GtmHeadlessResult
from app.services.stack_detector import StackDetection
from app.services.tls_check import TlsStatus
from tests.conftest import UserFactory, owner_workspace_id


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def _site(db_session, workspace_id, domain: str = "tool.test") -> Website:
    site = Website(workspace_id=workspace_id, domain=domain, display_name="Tool")
    db_session.add(site)
    await db_session.flush()
    return site


async def _thread(db_session, site: Website) -> AdvisorThread:
    thread = AdvisorThread(website_id=site.id, persona_key="consultant", title="Fil de test")
    db_session.add(thread)
    await db_session.flush()
    return thread


async def _fake_detector(url: str, **kw) -> StackDetection:
    _ = (url, kw)
    return StackDetection(StackKind.REACT, ("react-root-static",), 0.7)


async def _fake_tls(domain: str) -> TlsStatus:
    return TlsStatus(host=domain, status="valid", checked_at=datetime.now(UTC))


async def _fake_gtm(domain: str):
    _ = domain
    return None


async def _fake_headless_ok(url: str) -> GtmHeadlessResult:
    _ = url
    return GtmHeadlessResult(
        gtm_js_loaded=True,
        containers_initialised=("GTM-AAA1111",),
        datalayer_present=True,
        gtm_events=("gtm.js", "gtm.load"),
        requests_before_consent=True,
        csp_console_errors=(),
        findings=(),
        checked_at=datetime.now(UTC),
    )


async def _snapshot_with_gtm(db_session, site: Website) -> None:
    db_session.add(
        AuditSnapshot(
            website_id=site.id,
            captured_at=datetime.now(UTC),
            source=SnapshotSource.COMPOSITE,
            metrics={
                "ga4": {}, "gsc": {}, "cwv": {},
                "gtm": {
                    "containers": ["GTM-AAA1111"], "ga4_tags": [], "snippet_form": "standard",
                    "snippet_in_head": True, "data_layer_name": "dataLayer",
                    "consent_platform": None, "gtm_consent_gated": False,
                    "csp_present": False, "csp_allows_gtm": None, "csp_blocks_preview": None,
                    "server_side": False, "query_stripped_on_redirect": False,
                    "findings": [], "checked_at": datetime.now(UTC).isoformat(), "error": None,
                },
            },
        )
    )
    await db_session.flush()


async def test_get_score_history_clamps_days(db_session, make_user: UserFactory) -> None:
    user = await make_user(sub="tl-1")
    site = await _site(db_session, await owner_workspace_id(db_session, user))
    old = datetime.now(UTC) - timedelta(days=200)
    recent = datetime.now(UTC) - timedelta(days=5)
    for when, ga4 in ((old, 10), (recent, 80)):
        db_session.add(
            AuditSnapshot(
                website_id=site.id,
                captured_at=when,
                source=SnapshotSource.COMPOSITE,
                metrics={"ga4": {"score": ga4}},
            )
        )
    await db_session.flush()

    out = await dispatch(
        "get_score_history", {"days": 500}, ToolContext(session=db_session, website=site)
    )
    scores = [h["ga4"] for h in out["history"]]
    assert 80 in scores
    assert 10 not in scores  # 500 borne a 90 -> le snapshot a 200j est hors fenetre


async def test_get_score_history_default_days(db_session, make_user: UserFactory) -> None:
    user = await make_user(sub="tl-1b")
    site = await _site(db_session, await owner_workspace_id(db_session, user))
    out = await dispatch("get_score_history", {}, ToolContext(session=db_session, website=site))
    assert out == {"history": []}


async def test_get_snapshot_detail_defaults_to_latest(db_session, make_user: UserFactory) -> None:
    user = await make_user(sub="tl-2")
    site = await _site(db_session, await owner_workspace_id(db_session, user))
    db_session.add(
        AuditSnapshot(
            website_id=site.id,
            captured_at=datetime.now(UTC),
            source=SnapshotSource.COMPOSITE,
            metrics={"ga4": {"score": 42}},
        )
    )
    await db_session.flush()
    out = await dispatch(
        "get_snapshot_detail", {}, ToolContext(session=db_session, website=site)
    )
    assert out["metrics"]["ga4"]["score"] == 42


async def test_get_snapshot_detail_unknown_id_returns_error(
    db_session, make_user: UserFactory
) -> None:
    user = await make_user(sub="tl-3")
    site = await _site(db_session, await owner_workspace_id(db_session, user))
    out = await dispatch(
        "get_snapshot_detail",
        {"snapshot_id": str(uuid4())},
        ToolContext(session=db_session, website=site),
    )
    assert "error" in out


async def test_get_snapshot_detail_invalid_id_returns_error(
    db_session, make_user: UserFactory
) -> None:
    user = await make_user(sub="tl-3b")
    site = await _site(db_session, await owner_workspace_id(db_session, user))
    out = await dispatch(
        "get_snapshot_detail",
        {"snapshot_id": "not-a-uuid"},
        ToolContext(session=db_session, website=site),
    )
    assert "error" in out


async def test_get_gtm_check_reads_latest_snapshot(db_session, make_user: UserFactory) -> None:
    user = await make_user(sub="tl-4")
    site = await _site(db_session, await owner_workspace_id(db_session, user))
    db_session.add(
        AuditSnapshot(
            website_id=site.id,
            captured_at=datetime.now(UTC),
            source=SnapshotSource.COMPOSITE,
            metrics={"gtm": {"containers": ["GTM-X"], "findings": []}},
        )
    )
    await db_session.flush()
    out = await dispatch("get_gtm_check", {}, ToolContext(session=db_session, website=site))
    assert out["containers"] == ["GTM-X"]


async def test_get_gtm_check_no_snapshot_returns_error(db_session, make_user: UserFactory) -> None:
    user = await make_user(sub="tl-4b")
    site = await _site(db_session, await owner_workspace_id(db_session, user))
    out = await dispatch("get_gtm_check", {}, ToolContext(session=db_session, website=site))
    assert "error" in out


async def test_get_page_html_follows_same_site_redirect() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/a":
            return httpx.Response(302, headers={"Location": "https://site.test/b"})
        return httpx.Response(200, text="<html>b</html>")

    website = Website(domain="site.test", display_name="X")
    result = await _get_page_html(website, "/a", client=_client(handler))
    assert "b</html>" in result["html"]


async def test_get_page_html_rejects_redirect_off_domain() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        _ = request
        return httpx.Response(302, headers={"Location": "https://evil.test/steal"})

    website = Website(domain="site.test", display_name="X")
    result = await _get_page_html(website, "/a", client=_client(handler))
    assert result == {"error": "redirect_off_domain"}


async def test_get_page_html_rejects_private_ip_redirect() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        _ = request
        return httpx.Response(302, headers={"Location": "http://169.254.169.254/meta"})

    website = Website(domain="site.test", display_name="X")
    result = await _get_page_html(website, "/a", client=_client(handler))
    assert result["error"] == "redirect_off_domain"


async def test_get_page_html_protocol_relative_path_stays_on_domain() -> None:
    seen_hosts: list[str | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_hosts.append(request.url.host)
        return httpx.Response(200, text="ok")

    website = Website(domain="site.test", display_name="X")
    await _get_page_html(website, "//evil.test/x", client=_client(handler))
    assert seen_hosts == ["site.test"]


async def test_get_page_html_network_error_returns_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        _ = request
        raise httpx.ConnectError("down")

    website = Website(domain="site.test", display_name="X")
    result = await _get_page_html(website, "/a", client=_client(handler))
    assert result == {"error": "fetch_error"}


async def test_get_page_html_too_many_redirects() -> None:
    counter = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        _ = request
        counter["n"] += 1
        return httpx.Response(302, headers={"Location": f"https://site.test/step{counter['n']}"})

    website = Website(domain="site.test", display_name="X")
    result = await _get_page_html(website, "/a", client=_client(handler))
    assert result == {"error": "too_many_redirects"}


async def test_dispatch_unknown_tool() -> None:
    website = Website(domain="site.test", display_name="X")
    out = await dispatch("nope", {}, ToolContext(session=None, website=website))
    assert "error" in out


async def test_trigger_rescan_creates_snapshot(db_session, make_user: UserFactory) -> None:
    user = await make_user(sub="act-1")
    site = await _site(db_session, await owner_workspace_id(db_session, user), domain="rescan.test")
    thread = await _thread(db_session, site)
    ctx = ToolContext(
        session=db_session,
        website=site,
        user_id=user.id,
        thread_id=thread.id,
        probe=MockAuditProbe(),
        detector=_fake_detector,
        tls_checker=_fake_tls,
        gtm_checker=_fake_gtm,
    )
    out = await dispatch("trigger_rescan", {}, ctx)
    assert "snapshot_id" in out
    assert out["detected_stack"] == "react"


async def test_trigger_rescan_is_rate_limited(db_session, make_user: UserFactory) -> None:
    user = await make_user(sub="act-2")
    site = await _site(db_session, await owner_workspace_id(db_session, user), domain="rescan2.test")
    thread = await _thread(db_session, site)
    ctx = ToolContext(
        session=db_session,
        website=site,
        user_id=user.id,
        thread_id=thread.id,
        probe=MockAuditProbe(),
        detector=_fake_detector,
        tls_checker=_fake_tls,
        gtm_checker=_fake_gtm,
    )
    first = await dispatch("trigger_rescan", {}, ctx)
    assert "snapshot_id" in first
    second = await dispatch("trigger_rescan", {}, ctx)
    assert "error" in second

    calls = (
        await db_session.execute(
            select(AdvisorToolCall).where(AdvisorToolCall.thread_id == thread.id)
        )
    ).scalars().all()
    assert len(calls) == 1  # le 2e appel refuse n'a pas ajoute de ligne


async def test_trigger_rescan_missing_deps_returns_error(
    db_session, make_user: UserFactory
) -> None:
    user = await make_user(sub="act-3")
    site = await _site(db_session, await owner_workspace_id(db_session, user), domain="rescan3.test")
    thread = await _thread(db_session, site)
    ctx = ToolContext(session=db_session, website=site, user_id=user.id, thread_id=thread.id)
    out = await dispatch("trigger_rescan", {}, ctx)
    assert "error" in out


async def test_draft_gtm_snippet_purchase_for_nextjs(db_session, make_user: UserFactory) -> None:
    user = await make_user(sub="snip-1")
    site = await _site(db_session, await owner_workspace_id(db_session, user), domain="snip.test")
    site.detected_stack = StackKind.NEXTJS
    ctx = ToolContext(session=db_session, website=site)
    out = await dispatch("draft_gtm_snippet", {"event": "purchase"}, ctx)
    assert out["language"] in ("ts", "tsx", "js", "php")
    assert "dataLayer" in out["code"]
    assert out["target_path"]


async def test_draft_gtm_snippet_unknown_event_returns_error(
    db_session, make_user: UserFactory
) -> None:
    user = await make_user(sub="snip-2")
    site = await _site(db_session, await owner_workspace_id(db_session, user), domain="snip2.test")
    ctx = ToolContext(session=db_session, website=site)
    out = await dispatch("draft_gtm_snippet", {"event": "signup"}, ctx)
    assert "error" in out


async def test_run_gtm_headless_probe_updates_snapshot(
    db_session, make_user: UserFactory
) -> None:
    user = await make_user(sub="headless-1")
    site = await _site(db_session, await owner_workspace_id(db_session, user), domain="headless.test")
    await _snapshot_with_gtm(db_session, site)
    thread = await _thread(db_session, site)
    ctx = ToolContext(
        session=db_session,
        website=site,
        user_id=user.id,
        thread_id=thread.id,
        gtm_headless_verifier=_fake_headless_ok,
    )
    out = await dispatch("run_gtm_headless_probe", {}, ctx)
    assert out["gtm_js_loaded"] is True
    assert out["containers_initialised"] == ["GTM-AAA1111"]

    row = (
        await db_session.execute(
            select(AuditSnapshot).where(AuditSnapshot.website_id == site.id)
        )
    ).scalars().first()
    assert row.metrics["gtm"]["headless"]["gtm_js_loaded"] is True


async def test_run_gtm_headless_probe_is_rate_limited(
    db_session, make_user: UserFactory
) -> None:
    user = await make_user(sub="headless-2")
    site = await _site(db_session, await owner_workspace_id(db_session, user), domain="headless2.test")
    await _snapshot_with_gtm(db_session, site)
    thread = await _thread(db_session, site)
    ctx = ToolContext(
        session=db_session,
        website=site,
        user_id=user.id,
        thread_id=thread.id,
        gtm_headless_verifier=_fake_headless_ok,
    )
    first = await dispatch("run_gtm_headless_probe", {}, ctx)
    assert first.get("error") is None
    second = await dispatch("run_gtm_headless_probe", {}, ctx)
    assert "error" in second

    calls = (
        await db_session.execute(
            select(AdvisorToolCall).where(
                AdvisorToolCall.thread_id == thread.id,
                AdvisorToolCall.tool == "run_gtm_headless_probe",
            )
        )
    ).scalars().all()
    assert len(calls) == 1


async def test_run_gtm_headless_probe_missing_deps_returns_error(
    db_session, make_user: UserFactory
) -> None:
    user = await make_user(sub="headless-3")
    site = await _site(db_session, await owner_workspace_id(db_session, user), domain="headless3.test")
    await _snapshot_with_gtm(db_session, site)
    thread = await _thread(db_session, site)
    ctx = ToolContext(session=db_session, website=site, user_id=user.id, thread_id=thread.id)
    out = await dispatch("run_gtm_headless_probe", {}, ctx)
    assert "error" in out


async def test_run_gtm_headless_probe_no_static_check_returns_error(
    db_session, make_user: UserFactory
) -> None:
    user = await make_user(sub="headless-4")
    site = await _site(db_session, await owner_workspace_id(db_session, user), domain="headless4.test")
    thread = await _thread(db_session, site)
    ctx = ToolContext(
        session=db_session,
        website=site,
        user_id=user.id,
        thread_id=thread.id,
        gtm_headless_verifier=_fake_headless_ok,
    )
    out = await dispatch("run_gtm_headless_probe", {}, ctx)
    assert "error" in out
