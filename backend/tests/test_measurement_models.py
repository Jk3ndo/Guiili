from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.measurement_item_event import MeasurementItemEvent
from app.models.measurement_item_status import MeasurementItemStatus
from app.models.website import Website
from app.models.website_profile import WebsiteProfile
from tests.conftest import owner_workspace_id


async def _site(db_session: AsyncSession, make_user, domain: str) -> Website:
    user = await make_user(sub=f"mm-{domain}")
    workspace_id = await owner_workspace_id(db_session, user)
    site = Website(workspace_id=workspace_id, domain=domain, display_name=domain)
    db_session.add(site)
    await db_session.flush()
    return site


async def test_profile_and_status_roundtrip(db_session: AsyncSession, make_user) -> None:
    site = await _site(db_session, make_user, "mm-roundtrip.test")
    db_session.add(
        WebsiteProfile(
            website_id=site.id,
            detected_types=[{"type": "ecommerce", "confidence": 0.8, "signals": ["shopify"]}],
            params={"ads_conversion_id": "AW-123456789"},
        )
    )
    db_session.add(
        MeasurementItemStatus(
            website_id=site.id,
            item_id="gtm_installed",
            state="on_page",
            evidence={"containers": ["GTM-AAAA111"]},
            checked_at=datetime.now(UTC),
        )
    )
    await db_session.flush()

    profile = (
        await db_session.execute(select(WebsiteProfile).where(WebsiteProfile.website_id == site.id))
    ).scalar_one()
    assert profile.confirmed_types is None
    assert profile.params == {"ads_conversion_id": "AW-123456789"}
    assert profile.headless_result is None

    row = (
        await db_session.execute(
            select(MeasurementItemStatus).where(MeasurementItemStatus.website_id == site.id)
        )
    ).scalar_one()
    assert row.evidence == {"containers": ["GTM-AAAA111"]}
    assert row.dismissed_at is None
    assert row.reason is None


async def test_status_primary_key_is_unique_per_site_and_item(
    db_session: AsyncSession, make_user
) -> None:
    site = await _site(db_session, make_user, "mm-unique.test")
    now = datetime.now(UTC)
    db_session.add(
        MeasurementItemStatus(
            website_id=site.id, item_id="ga4_tag", state="missing", evidence={}, checked_at=now
        )
    )
    await db_session.flush()
    db_session.add(
        MeasurementItemStatus(
            website_id=site.id, item_id="ga4_tag", state="on_page", evidence={}, checked_at=now
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_rows_are_deleted_with_the_website(db_session: AsyncSession, make_user) -> None:
    site = await _site(db_session, make_user, "mm-cascade.test")
    db_session.add(WebsiteProfile(website_id=site.id, detected_types=[], params={}))
    db_session.add(
        MeasurementItemStatus(
            website_id=site.id,
            item_id="gtm_installed",
            state="missing",
            evidence={},
            checked_at=datetime.now(UTC),
        )
    )
    await db_session.flush()

    await db_session.delete(site)
    await db_session.flush()
    db_session.expunge_all()

    assert (await db_session.execute(select(WebsiteProfile))).first() is None
    assert (await db_session.execute(select(MeasurementItemStatus))).first() is None


async def test_events_keep_the_state_history_in_order_and_cascade(
    db_session: AsyncSession, make_user
) -> None:
    site = await _site(db_session, make_user, "mm-events.test")
    start = datetime.now(UTC)
    db_session.add_all(
        [
            MeasurementItemEvent(
                website_id=site.id,
                item_id="gtm_installed",
                from_state="missing",
                to_state="on_page",
                at=start + timedelta(minutes=5),
                evidence={"containers": ["GTM-AAAA111"]},
            ),
            MeasurementItemEvent(
                website_id=site.id,
                item_id="gtm_installed",
                from_state=None,
                to_state="missing",
                at=start,
                evidence={},
            ),
        ]
    )
    await db_session.flush()

    rows = (
        await db_session.execute(
            select(MeasurementItemEvent)
            .where(MeasurementItemEvent.website_id == site.id)
            .order_by(MeasurementItemEvent.at)
        )
    ).scalars().all()
    assert [(row.from_state, row.to_state) for row in rows] == [
        (None, "missing"),
        ("missing", "on_page"),
    ]
    assert rows[1].evidence == {"containers": ["GTM-AAAA111"]}

    await db_session.delete(site)
    await db_session.flush()
    db_session.expunge_all()
    assert (await db_session.execute(select(MeasurementItemEvent))).first() is None
