from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx

from app.models.audit_snapshot import AuditSnapshot
from app.models.enums import SnapshotSource
from app.models.website import Website
from app.services.advisor.tools import _get_page_html, dispatch
from tests.conftest import UserFactory


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def _site(db_session, user_id, domain: str = "tool.test") -> Website:
    site = Website(user_id=user_id, domain=domain, display_name="Tool")
    db_session.add(site)
    await db_session.flush()
    return site


async def test_get_score_history_clamps_days(db_session, make_user: UserFactory) -> None:
    user = await make_user(sub="tl-1")
    site = await _site(db_session, user.id)
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

    out = await dispatch("get_score_history", {"days": 500}, session=db_session, website=site)
    scores = [h["ga4"] for h in out["history"]]
    assert 80 in scores
    assert 10 not in scores  # 500 borne a 90 -> le snapshot a 200j est hors fenetre


async def test_get_score_history_default_days(db_session, make_user: UserFactory) -> None:
    user = await make_user(sub="tl-1b")
    site = await _site(db_session, user.id)
    out = await dispatch("get_score_history", {}, session=db_session, website=site)
    assert out == {"history": []}


async def test_get_snapshot_detail_defaults_to_latest(db_session, make_user: UserFactory) -> None:
    user = await make_user(sub="tl-2")
    site = await _site(db_session, user.id)
    db_session.add(
        AuditSnapshot(
            website_id=site.id,
            captured_at=datetime.now(UTC),
            source=SnapshotSource.COMPOSITE,
            metrics={"ga4": {"score": 42}},
        )
    )
    await db_session.flush()
    out = await dispatch("get_snapshot_detail", {}, session=db_session, website=site)
    assert out["metrics"]["ga4"]["score"] == 42


async def test_get_snapshot_detail_unknown_id_returns_error(
    db_session, make_user: UserFactory
) -> None:
    user = await make_user(sub="tl-3")
    site = await _site(db_session, user.id)
    out = await dispatch(
        "get_snapshot_detail", {"snapshot_id": str(uuid4())}, session=db_session, website=site
    )
    assert "error" in out


async def test_get_snapshot_detail_invalid_id_returns_error(
    db_session, make_user: UserFactory
) -> None:
    user = await make_user(sub="tl-3b")
    site = await _site(db_session, user.id)
    out = await dispatch(
        "get_snapshot_detail", {"snapshot_id": "not-a-uuid"}, session=db_session, website=site
    )
    assert "error" in out


async def test_get_gtm_check_reads_latest_snapshot(db_session, make_user: UserFactory) -> None:
    user = await make_user(sub="tl-4")
    site = await _site(db_session, user.id)
    db_session.add(
        AuditSnapshot(
            website_id=site.id,
            captured_at=datetime.now(UTC),
            source=SnapshotSource.COMPOSITE,
            metrics={"gtm": {"containers": ["GTM-X"], "findings": []}},
        )
    )
    await db_session.flush()
    out = await dispatch("get_gtm_check", {}, session=db_session, website=site)
    assert out["containers"] == ["GTM-X"]


async def test_get_gtm_check_no_snapshot_returns_error(db_session, make_user: UserFactory) -> None:
    user = await make_user(sub="tl-4b")
    site = await _site(db_session, user.id)
    out = await dispatch("get_gtm_check", {}, session=db_session, website=site)
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
    out = await dispatch("nope", {}, session=None, website=website)
    assert "error" in out
