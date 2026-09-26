from datetime import UTC, date, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.metric_rollup import MetricRollup
from app.services.metrics.registry import METRICS_BY_KEY
from app.services.metrics.series import build_series, comparison_range, freshness, shift_year
from app.services.metrics.store import store_observations
from app.services.metrics.types import Observation
from tests.jobs_fakes import make_site

NOW = datetime(2026, 9, 26, 6, 0, tzinfo=UTC)
SESSIONS = METRICS_BY_KEY["ga4.sessions"]


async def _store(session: AsyncSession, site, source: str, observations) -> None:
    await store_observations(
        session, website_id=site.id, source=source, observations=observations, run_id=None, now=NOW
    )


def test_comparison_ranges() -> None:
    assert comparison_range(date(2026, 9, 1), date(2026, 9, 7), "none") is None
    assert comparison_range(date(2026, 9, 8), date(2026, 9, 14), "previous_period") == (
        date(2026, 9, 1), date(2026, 9, 7),
    )
    assert comparison_range(date(2026, 9, 1), date(2026, 9, 7), "previous_year") == (
        date(2025, 9, 1), date(2025, 9, 7),
    )
    assert shift_year(date(2028, 2, 29)) == date(2027, 2, 28)


async def test_daily_series_shows_gaps_as_null(db_session: AsyncSession, make_user) -> None:
    site = await make_site(db_session, make_user, "series-day.test")
    await _store(db_session, site, "ga4", [
        Observation("sessions", date(2026, 9, 21), 5.0),
        Observation("sessions", date(2026, 9, 23), 7.0),
    ])
    series = await build_series(
        db_session, website_id=site.id, defn=SESSIONS,
        start=date(2026, 9, 21), end=date(2026, 9, 23), granularity="day",
    )
    assert [(p.period_start, p.value, p.days_covered) for p in series.points] == [
        (date(2026, 9, 21), 5.0, 1),
        (date(2026, 9, 22), None, 0),
        (date(2026, 9, 23), 7.0, 1),
    ]
    assert series.total == 12.0


async def test_full_weeks_come_from_the_rollups_and_edges_from_the_points(
    db_session: AsyncSession, make_user
) -> None:
    site = await make_site(db_session, make_user, "series-week.test")
    await _store(db_session, site, "ga4", [
        Observation("sessions", date(2026, 9, 20), 1.0),  # dimanche : semaine du 14 (bord)
        Observation("sessions", date(2026, 9, 21), 2.0),  # semaine du 21 (entière)
        Observation("sessions", date(2026, 9, 22), 3.0),
    ])
    # Preuve de lecture des cumuls : on remplace le cumul de la semaine entière.
    rollup = await db_session.get(
        MetricRollup, (site.id, "ga4", "sessions", "", "week", date(2026, 9, 21))
    )
    rollup.value = 999.0
    await db_session.flush()
    series = await build_series(
        db_session, website_id=site.id, defn=SESSIONS,
        start=date(2026, 9, 20), end=date(2026, 9, 27), granularity="week",
    )
    edge, full = series.points
    assert (edge.period_start, edge.value, edge.days_covered, edge.days_expected) == (
        date(2026, 9, 14), 1.0, 1, 1,
    )
    assert (full.period_start, full.value, full.days_covered, full.days_expected) == (
        date(2026, 9, 21), 999.0, 2, 7,
    )


async def test_ratio_metrics_are_recomputed_from_their_parts(
    db_session: AsyncSession, make_user
) -> None:
    site = await make_site(db_session, make_user, "series-ctr.test")
    await _store(db_session, site, "gsc", [
        Observation("clicks", date(2026, 9, 21), 10.0),
        Observation("impressions", date(2026, 9, 21), 100.0),
        Observation("ctr", date(2026, 9, 21), 0.1),
        Observation("clicks", date(2026, 9, 22), 30.0),
        Observation("impressions", date(2026, 9, 22), 100.0),
        Observation("ctr", date(2026, 9, 22), 0.3),
    ])
    series = await build_series(
        db_session, website_id=site.id, defn=METRICS_BY_KEY["gsc.ctr"],
        start=date(2026, 9, 21), end=date(2026, 9, 22), granularity="month",
    )
    assert series.total == pytest.approx(0.2)
    assert series.points[0].value == pytest.approx(0.2)


async def test_freshness_reports_the_last_collection(db_session: AsyncSession, make_user) -> None:
    site = await make_site(db_session, make_user, "series-fresh.test")
    assert await freshness(db_session, site.id, "ga4") == (None, None)
    await _store(db_session, site, "ga4", [Observation("sessions", date(2026, 9, 25), 1.0)])
    fresh = await freshness(db_session, site.id, "ga4")
    assert fresh.last_collected_at == NOW and fresh.data_until == date(2026, 9, 25)
