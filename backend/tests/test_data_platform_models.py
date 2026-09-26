from datetime import UTC, date, datetime

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.job_run import JobRun
from app.models.metric_point import DEFAULT_PARTITION, MetricPoint
from app.models.metric_rollup import MetricRollup
from app.models.schedule import Schedule
from app.models.website import Website
from tests.conftest import owner_workspace_id

NOW = datetime(2026, 9, 26, 6, 0, tzinfo=UTC)


async def _site(db_session: AsyncSession, make_user, domain: str) -> Website:
    user = await make_user(sub=f"dp-{domain}")
    workspace_id = await owner_workspace_id(db_session, user)
    site = Website(workspace_id=workspace_id, domain=domain, display_name=domain)
    db_session.add(site)
    await db_session.flush()
    return site


def _point(site: Website, **overrides) -> MetricPoint:
    values = {
        "website_id": site.id,
        "source": "ga4",
        "metric": "sessions",
        "dim_key": "",
        "day": date(2026, 9, 20),
        "value": 12.0,
        "dims": {},
        "collected_at": NOW,
    }
    values.update(overrides)
    return MetricPoint(**values)


async def test_a_metric_point_lands_in_the_default_partition(
    db_session: AsyncSession, make_user
) -> None:
    site = await _site(db_session, make_user, "dp-default.test")
    db_session.add(_point(site))
    await db_session.flush()
    where = await db_session.scalar(
        text("SELECT tableoid::regclass::text FROM metric_points WHERE website_id = :w"),
        {"w": site.id},
    )
    assert where == DEFAULT_PARTITION
    row = (
        await db_session.execute(select(MetricPoint).where(MetricPoint.website_id == site.id))
    ).scalar_one()
    assert row.value == 12.0 and row.run_id is None and row.dims == {}


async def test_the_primary_key_makes_a_day_unique_per_series(
    db_session: AsyncSession, make_user
) -> None:
    site = await _site(db_session, make_user, "dp-unique.test")
    db_session.add(_point(site))
    await db_session.flush()
    db_session.add(_point(site, value=99.0))
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_a_schedule_is_unique_per_site_and_kind(
    db_session: AsyncSession, make_user
) -> None:
    site = await _site(db_session, make_user, "dp-schedule.test")
    for _ in range(2):
        db_session.add(
            Schedule(
                website_id=site.id,
                kind="collect_ga4",
                frequency="daily",
                enabled=True,
                next_due_at=NOW,
            )
        )
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_a_job_run_idempotency_key_is_unique(
    db_session: AsyncSession, make_user
) -> None:
    site = await _site(db_session, make_user, "dp-run.test")
    for _ in range(2):
        db_session.add(
            JobRun(
                idempotency_key=f"collect_ga4:{site.id}:20260926T0000",
                kind="collect_ga4",
                website_id=site.id,
                workspace_id=site.workspace_id,
                window_label="20260926T0000",
                params={},
                status="queued",
                attempt=0,
                max_attempts=5,
                observations=0,
            )
        )
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_every_lot_b_row_is_deleted_with_the_website(
    db_session: AsyncSession, make_user
) -> None:
    site = await _site(db_session, make_user, "dp-cascade.test")
    db_session.add_all(
        [
            _point(site),
            MetricRollup(
                website_id=site.id,
                source="ga4",
                metric="sessions",
                dim_key="",
                grain="week",
                period_start=date(2026, 9, 14),
                value=40.0,
                days_covered=4,
                dims={},
                updated_at=NOW,
            ),
            Schedule(
                website_id=site.id,
                kind="collect_ga4",
                frequency="daily",
                enabled=True,
                next_due_at=NOW,
            ),
            JobRun(
                idempotency_key=f"collect_ga4:{site.id}:w",
                kind="collect_ga4",
                website_id=site.id,
                workspace_id=site.workspace_id,
                window_label="w",
                params={},
                status="succeeded",
                attempt=1,
                max_attempts=5,
                observations=3,
            ),
        ]
    )
    await db_session.flush()

    await db_session.delete(site)
    await db_session.flush()
    db_session.expunge_all()

    for model in (MetricPoint, MetricRollup, Schedule, JobRun):
        assert await db_session.scalar(select(func.count()).select_from(model)) == 0, model
