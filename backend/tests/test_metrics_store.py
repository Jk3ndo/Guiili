from datetime import UTC, date, datetime
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.metric_point import MetricPoint
from app.models.metric_rollup import MetricRollup
from app.models.website import Website
from app.services.metrics.store import prepare_rows, store_observations
from app.services.metrics.types import Observation
from tests.conftest import owner_workspace_id

NOW = datetime(2026, 9, 26, 6, 0, tzinfo=UTC)
MON, TUE = date(2026, 9, 21), date(2026, 9, 22)


def _obs(metric: str, day: date, value: float, **dims: str) -> Observation:
    return Observation(metric, day, value, dict(dims))


def _non_finite(metric: str, day: date) -> Observation:
    # `Observation` refuse une valeur non finie à la construction : on la force après
    # coup pour prouver que le stockage se protège aussi seul.
    obs = Observation(metric, day, 1.0)
    object.__setattr__(obs, "value", float("nan"))
    return obs


async def _site(db_session: AsyncSession, make_user, domain: str) -> Website:
    user = await make_user(sub=f"store-{domain}")
    workspace_id = await owner_workspace_id(db_session, user)
    site = Website(workspace_id=workspace_id, domain=domain, display_name=domain)
    db_session.add(site)
    await db_session.flush()
    return site


async def _points(db_session: AsyncSession, website_id) -> list[tuple]:
    rows = await db_session.execute(
        select(
            MetricPoint.source, MetricPoint.metric, MetricPoint.dims, MetricPoint.day,
            MetricPoint.value,
        )
        .where(MetricPoint.website_id == website_id)
        .order_by(MetricPoint.metric, MetricPoint.day, MetricPoint.dim_key)
    )
    return [tuple(row) for row in rows.all()]


async def _rollups(db_session: AsyncSession, website_id) -> dict[tuple[str, str, date], tuple]:
    rows = await db_session.execute(
        select(MetricRollup).where(MetricRollup.website_id == website_id, MetricRollup.dim_key == "")
    )
    return {
        (r.metric, r.grain, r.period_start): (r.value, r.days_covered) for r in rows.scalars()
    }


def test_prepare_rows_validates_and_cleans() -> None:
    observations = [
        _obs("sessions", MON, 10),
        _obs("inconnue", MON, 1),  # métrique hors registre
        _non_finite("sessions", TUE),  # valeur non finie
        _obs("event_count", MON, 5, event_name="purchase"),
        _obs("event_count", MON, 3, event_name="nom invalide !"),  # nom GA4 invalide
        _obs("event_count", MON, 2, page="/x"),  # dimension non permise pour GA4
    ]
    rows, dropped = prepare_rows(
        website_id=uuid4(), source="ga4", observations=observations, run_id=None, now=NOW
    )
    assert dropped == 4
    assert [(r["metric"], r["dims"], r["day"]) for r in rows] == [
        ("event_count", {"event_name": "purchase"}, MON),
        ("sessions", {}, MON),
    ]
    assert rows[1]["dim_key"] == "" and rows[0]["dim_key"] != ""


def test_a_discarded_dimension_value_never_becomes_a_total() -> None:
    observations = [
        _obs("clicks", MON, 7.0, page="//evil.example/x"),
        _obs("clicks", MON, 4.0, query="jean@example.com"),
    ]
    rows, dropped = prepare_rows(
        website_id=uuid4(), source="gsc", observations=observations, run_id=None, now=NOW
    )
    assert rows == [] and dropped == 2


def test_prepare_rows_keeps_the_top_n_per_day_and_dimension() -> None:
    observations = [_obs("clicks", MON, float(i), page=f"/p{i:02d}") for i in range(30)]
    observations.append(_obs("clicks", MON, 99.0))  # le total n'est jamais plafonné
    rows, dropped = prepare_rows(
        website_id=uuid4(), source="gsc", observations=observations, run_id=None, now=NOW
    )
    assert dropped == 5
    pages = {r["dims"]["page"] for r in rows if r["dims"]}
    assert pages == {f"/p{i:02d}" for i in range(5, 30)}
    assert any(r["dims"] == {} and r["value"] == 99.0 for r in rows)


def test_prepare_rows_cleans_pages_before_capping() -> None:
    observations = [_obs("clicks", MON, 3.0, page="https://x.fr/panier?id=1")]
    rows, dropped = prepare_rows(
        website_id=uuid4(), source="gsc", observations=observations, run_id=None, now=NOW
    )
    assert dropped == 0 and rows[0]["dims"] == {"page": "/panier"}


def test_values_converging_after_cleaning_are_summed_not_overwritten() -> None:
    observations = [
        _obs("clicks", MON, 3.0, page="/panier?id=1"),
        _obs("clicks", MON, 4.0, page="/panier?id=2"),
        _obs("clicks", MON, 5.0, page="https://x.fr/panier#haut"),
        _obs("impressions", MON, 10.0, query="Chaussure  Rouge"),
        _obs("impressions", MON, 6.0, query="chaussure rouge"),
    ]
    rows, dropped = prepare_rows(
        website_id=uuid4(), source="gsc", observations=observations, run_id=None, now=NOW
    )
    assert dropped == 0
    assert [(r["metric"], r["dims"], r["value"]) for r in rows] == [
        ("clicks", {"page": "/panier"}, 12.0),
        ("impressions", {"query": "chaussure rouge"}, 16.0),
    ]


async def test_converging_values_are_stored_in_one_statement_without_error(
    db_session: AsyncSession, make_user
) -> None:
    site = await _site(db_session, make_user, "store-converge.test")
    result = await store_observations(
        db_session, website_id=site.id, source="gsc", run_id=None, now=NOW,
        observations=[
            _obs("clicks", MON, 3.0, page="/panier?id=1"),
            _obs("clicks", MON, 4.0, page="/panier?id=2"),
        ],
    )
    assert result.written == 1
    assert await _points(db_session, site.id) == [
        ("gsc", "clicks", {"page": "/panier"}, MON, 7.0)
    ]


async def test_storing_the_same_observations_twice_gives_the_same_rows(
    db_session: AsyncSession, make_user
) -> None:
    site = await _site(db_session, make_user, "store-idem.test")
    run_id = uuid4()
    observations = [
        _obs("clicks", MON, 4, page="/a"),
        _obs("clicks", MON, 2, page="/b"),
        _obs("clicks", MON, 6),
        _obs("impressions", MON, 60),
    ]
    first = await store_observations(
        db_session, website_id=site.id, source="gsc", observations=observations,
        run_id=run_id, now=NOW,
    )
    snapshot = await _points(db_session, site.id)
    second = await store_observations(
        db_session, website_id=site.id, source="gsc", observations=observations,
        run_id=run_id, now=NOW,
    )
    assert await _points(db_session, site.id) == snapshot
    assert first.written == second.written == 4
    assert first.days == frozenset({MON})
    stored_run = await db_session.scalar(
        select(MetricPoint.run_id).where(MetricPoint.website_id == site.id).limit(1)
    )
    assert stored_run == run_id


async def test_a_replay_removes_dimension_rows_that_left_the_top(
    db_session: AsyncSession, make_user
) -> None:
    site = await _site(db_session, make_user, "store-replay.test")
    await store_observations(
        db_session, website_id=site.id, source="gsc",
        observations=[_obs("clicks", MON, 4, page="/a"), _obs("clicks", MON, 2, page="/b")],
        run_id=None, now=NOW,
    )
    await store_observations(
        db_session, website_id=site.id, source="gsc",
        observations=[_obs("clicks", MON, 5, page="/a")], run_id=None, now=NOW,
    )
    assert await _points(db_session, site.id) == [
        ("gsc", "clicks", {"page": "/a"}, MON, 5.0)
    ]


async def test_a_day_missing_from_a_new_collection_is_kept(
    db_session: AsyncSession, make_user
) -> None:
    site = await _site(db_session, make_user, "store-keep.test")
    await store_observations(
        db_session, website_id=site.id, source="ga4",
        observations=[_obs("sessions", MON, 3), _obs("sessions", TUE, 4)],
        run_id=None, now=NOW,
    )
    await store_observations(
        db_session, website_id=site.id, source="ga4",
        observations=[_obs("sessions", TUE, 5)], run_id=None, now=NOW,
    )
    values = {row[3]: row[4] for row in await _points(db_session, site.id)}
    assert values == {MON: 3.0, TUE: 5.0}


async def test_an_empty_or_fully_rejected_collection_erases_nothing(
    db_session: AsyncSession, make_user
) -> None:
    site = await _site(db_session, make_user, "store-empty.test")
    await store_observations(
        db_session, website_id=site.id, source="ga4",
        observations=[_obs("sessions", MON, 3)], run_id=None, now=NOW,
    )
    result = await store_observations(
        db_session, website_id=site.id, source="ga4",
        observations=[_obs("inconnue", MON, 1)], run_id=None, now=NOW,
    )
    assert result.written == 0 and result.dropped == 1 and result.days == frozenset()
    assert len(await _points(db_session, site.id)) == 1


async def test_rollups_use_the_registry_aggregations(
    db_session: AsyncSession, make_user
) -> None:
    site = await _site(db_session, make_user, "store-rollup.test")
    observations = [
        _obs("clicks", MON, 10), _obs("clicks", TUE, 30),
        _obs("impressions", MON, 100), _obs("impressions", TUE, 300),
        _obs("ctr", MON, 0.1), _obs("ctr", TUE, 0.1),
        _obs("position", MON, 10.0), _obs("position", TUE, 20.0),
    ]
    await store_observations(
        db_session, website_id=site.id, source="gsc", observations=observations,
        run_id=None, now=NOW,
    )
    rollups = await _rollups(db_session, site.id)
    week, month = date(2026, 9, 21), date(2026, 9, 1)
    for grain, start in (("week", week), ("month", month)):
        assert rollups[("clicks", grain, start)] == (40.0, 2)
        assert rollups[("impressions", grain, start)] == (400.0, 2)
        assert rollups[("ctr", grain, start)][0] == pytest.approx(0.1)
        # Moyenne pondérée par les impressions : (10*100 + 20*300) / 400.
        assert rollups[("position", grain, start)][0] == pytest.approx(17.5)


async def test_derived_rollups_ignore_dimension_series(
    db_session: AsyncSession, make_user
) -> None:
    site = await _site(db_session, make_user, "store-derived.test")
    await store_observations(
        db_session, website_id=site.id, source="gsc", run_id=None, now=NOW,
        observations=[
            _obs("clicks", MON, 10), _obs("clicks", MON, 4, page="/a"),
            _obs("impressions", MON, 100), _obs("impressions", MON, 900, page="/a"),
            _obs("ctr", MON, 0.1),
            _obs("position", MON, 5.0),
        ],
    )
    rollups = await _rollups(db_session, site.id)
    week = date(2026, 9, 21)
    assert rollups[("clicks", "week", week)] == (10.0, 1)
    assert rollups[("position", "week", week)][0] == pytest.approx(5.0)
    paged = await db_session.scalar(
        select(MetricRollup.value).where(
            MetricRollup.website_id == site.id,
            MetricRollup.metric == "clicks",
            MetricRollup.dim_key != "",
            MetricRollup.grain == "week",
        )
    )
    assert paged == 4.0


async def test_rollups_report_partial_periods_through_days_covered(
    db_session: AsyncSession, make_user
) -> None:
    site = await _site(db_session, make_user, "store-partial.test")
    await store_observations(
        db_session, website_id=site.id, source="ga4",
        observations=[_obs("sessions", MON, 3), _obs("sessions", date(2026, 9, 24), 4)],
        run_id=None, now=NOW,
    )
    rollups = await _rollups(db_session, site.id)
    assert rollups[("sessions", "week", MON)] == (7.0, 2)
    assert rollups[("sessions", "month", date(2026, 9, 1))] == (7.0, 2)


async def test_rollups_are_recomputed_after_a_replay(
    db_session: AsyncSession, make_user
) -> None:
    site = await _site(db_session, make_user, "store-rollup-replay.test")
    for value in (3.0, 8.0):
        await store_observations(
            db_session, website_id=site.id, source="ga4",
            observations=[_obs("sessions", MON, value), _obs("sessions", TUE, 1.0)],
            run_id=None, now=NOW,
        )
    rollups = await _rollups(db_session, site.id)
    assert rollups[("sessions", "week", date(2026, 9, 21))] == (9.0, 2)
