from uuid import UUID

import pytest
from sqlalchemy import select
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import ResourceType
from app.models.google_connection import GoogleConnection
from app.models.website import Website
from app.models.website_google_link import WebsiteGoogleLink
from tests.conftest import owner_workspace_id


async def _seed(session: AsyncSession, make_user) -> tuple[UUID, GoogleConnection]:
    user = await make_user(sub="sub-w", email="u@example.com")
    workspace_id = await owner_workspace_id(session, user)
    conn = GoogleConnection(
        workspace_id=workspace_id,
        google_account_email="acct@example.com",
        google_sub="g-w",
        granted_scopes=["openid"],
        refresh_token_encrypted=b"x",
        encryption_key_version=1,
    )
    session.add(conn)
    await session.flush()
    return workspace_id, conn


async def test_website_unique_user_domain(db_session: AsyncSession, make_user) -> None:
    workspace_id, _ = await _seed(db_session, make_user)
    db_session.add(Website(workspace_id=workspace_id, domain="ex.com", display_name="Ex"))
    await db_session.flush()
    db_session.add(Website(workspace_id=workspace_id, domain="ex.com", display_name="Ex2"))
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_link_multi_resource_per_website(db_session: AsyncSession, make_user) -> None:
    workspace_id, conn = await _seed(db_session, make_user)
    site = Website(workspace_id=workspace_id, domain="ex.com", display_name="Ex")
    db_session.add(site)
    await db_session.flush()
    db_session.add_all(
        [
            WebsiteGoogleLink(
                website_id=site.id,
                google_connection_id=conn.id,
                resource_type=ResourceType.GA4_PROPERTY,
                resource_id="properties/123",
            ),
            WebsiteGoogleLink(
                website_id=site.id,
                google_connection_id=conn.id,
                resource_type=ResourceType.GSC_SITE,
                resource_id="sc-domain:ex.com",
            ),
        ]
    )
    await db_session.flush()
    links = (await db_session.execute(select(WebsiteGoogleLink))).scalars().all()
    assert {link.resource_type for link in links} == {
        ResourceType.GA4_PROPERTY,
        ResourceType.GSC_SITE,
    }


async def test_link_rejects_invalid_resource_type(db_session: AsyncSession, make_user) -> None:
    workspace_id, conn = await _seed(db_session, make_user)
    site = Website(workspace_id=workspace_id, domain="ex.com", display_name="Ex")
    db_session.add(site)
    await db_session.flush()
    db_session.add(
        WebsiteGoogleLink(
            website_id=site.id,
            google_connection_id=conn.id,
            resource_type="not_a_type",  # viole le CHECK
            resource_id="x",
        )
    )
    with pytest.raises((IntegrityError, DBAPIError)):
        await db_session.flush()


async def test_website_delete_cascades_links(db_session: AsyncSession, make_user) -> None:
    workspace_id, conn = await _seed(db_session, make_user)
    site = Website(workspace_id=workspace_id, domain="ex.com", display_name="Ex")
    db_session.add(site)
    await db_session.flush()
    db_session.add(
        WebsiteGoogleLink(
            website_id=site.id,
            google_connection_id=conn.id,
            resource_type=ResourceType.GA4_PROPERTY,
            resource_id="properties/123",
        )
    )
    await db_session.flush()
    await db_session.delete(site)
    await db_session.flush()
    links = (await db_session.execute(select(WebsiteGoogleLink))).scalars().all()
    assert links == []
