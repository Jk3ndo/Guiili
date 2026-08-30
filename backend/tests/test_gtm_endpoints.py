"""Endpoints GTM : export (telechargement + audit_log) et snippets."""

import json

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_log import AuditLog
from app.models.enums import ResourceType, StackKind
from app.models.google_connection import GoogleConnection
from app.models.user import User
from app.models.website import Website
from app.models.website_google_link import WebsiteGoogleLink


async def _website(
    session: AsyncSession, *, user: User, domain: str, stack: StackKind | None = None
) -> Website:
    site = Website(user_id=user.id, domain=domain, display_name=domain, detected_stack=stack)
    session.add(site)
    await session.flush()
    return site


async def test_gtm_export_downloads_valid_container(
    authed_client: tuple[AsyncClient, User], db_session: AsyncSession
) -> None:
    client, user = authed_client
    site = await _website(db_session, user=user, domain="boutique-verte.fr", stack=StackKind.NEXTJS)

    resp = await client.get(f"/api/v1/websites/{site.id}/gtm-export")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/json")
    assert (
        resp.headers["content-disposition"]
        == 'attachment; filename="gtm-container-boutique-verte.fr.json"'
    )

    container = json.loads(resp.text)
    assert container["exportFormatVersion"] == 2
    assert any(t["name"] == "GA4 Configuration" for t in container["containerVersion"]["tag"])

    log = (
        await db_session.execute(select(AuditLog).where(AuditLog.resource_id == str(site.id)))
    ).scalar_one()
    assert log.action == "gtm.container_exported"
    assert len(log.request_payload_hash) == 64


async def test_gtm_export_overwrite_mode(
    authed_client: tuple[AsyncClient, User], db_session: AsyncSession
) -> None:
    client, user = authed_client
    site = await _website(db_session, user=user, domain="x.test")

    resp = await client.get(f"/api/v1/websites/{site.id}/gtm-export?mode=overwrite")
    assert resp.status_code == 200
    assert json.loads(resp.text)["importMetadata"]["mode"] == "overwrite"


async def test_gtm_export_uses_linked_ga4_property(
    authed_client: tuple[AsyncClient, User], db_session: AsyncSession
) -> None:
    client, user = authed_client
    site = await _website(db_session, user=user, domain="linked.test")
    conn = GoogleConnection(
        user_id=user.id,
        google_account_email="a@gmail.com",
        google_sub="sub-gtm",
        granted_scopes=["openid"],
        refresh_token_encrypted=b"x",
        encryption_key_version=1,
    )
    db_session.add(conn)
    await db_session.flush()
    db_session.add(
        WebsiteGoogleLink(
            website_id=site.id,
            google_connection_id=conn.id,
            resource_type=ResourceType.GA4_PROPERTY,
            resource_id="properties/447213908",
        )
    )
    await db_session.flush()

    resp = await client.get(f"/api/v1/websites/{site.id}/gtm-export")
    assert "properties/447213908" in json.loads(resp.text)["containerVersion"]["description"]


async def test_snippets_match_detected_stack(
    authed_client: tuple[AsyncClient, User], db_session: AsyncSession
) -> None:
    client, user = authed_client
    site = await _website(db_session, user=user, domain="shop.test", stack=StackKind.WOOCOMMERCE)

    resp = await client.get(f"/api/v1/websites/{site.id}/snippets")
    assert resp.status_code == 200
    body = resp.json()
    assert body["detected_stack"] == "woocommerce"
    assert body["resolved_stack"] == "woocommerce"
    assert {e["event"] for e in body["entries"]} == {"purchase", "lead", "custom"}
    purchase = next(e for e in body["entries"] if e["event"] == "purchase")
    assert "woocommerce_thankyou" in purchase["code"]


async def test_snippets_event_filter_and_unknown_stack(
    authed_client: tuple[AsyncClient, User], db_session: AsyncSession
) -> None:
    client, user = authed_client
    site = await _website(db_session, user=user, domain="plain.test")  # stack None

    resp = await client.get(f"/api/v1/websites/{site.id}/snippets?event=lead")
    body = resp.json()
    assert body["detected_stack"] is None
    assert body["resolved_stack"] == "unknown"
    assert len(body["entries"]) == 1
    assert body["entries"][0]["event"] == "lead"
    assert body["entries"][0]["language"] == "js"


async def test_gtm_endpoints_ownership_and_auth(
    authed_client: tuple[AsyncClient, User], db_session: AsyncSession, make_user
) -> None:
    client, _user = authed_client
    stranger = await make_user(sub="stranger-gtm")
    foreign = await _website(db_session, user=stranger, domain="notyours.test")

    assert (await client.get(f"/api/v1/websites/{foreign.id}/gtm-export")).status_code == 404
    assert (await client.get(f"/api/v1/websites/{foreign.id}/snippets")).status_code == 404


async def test_gtm_requires_auth(db_client: AsyncClient) -> None:
    fake = "00000000-0000-0000-0000-000000000000"
    assert (await db_client.get(f"/api/v1/websites/{fake}/gtm-export")).status_code == 401
    assert (await db_client.get(f"/api/v1/websites/{fake}/snippets")).status_code == 401
