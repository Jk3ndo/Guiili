from datetime import UTC, date, datetime

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.metric_point import DEFAULT_PARTITION, MetricPoint
from app.models.website import Website
from app.services.metrics.partitions import (
    add_months,
    ensure_partitions,
    list_partitions,
    partition_name,
    purge_expired,
)
from tests.conftest import owner_workspace_id

TODAY = date(2026, 9, 26)
NOW = datetime(2026, 9, 26, 6, 0, tzinfo=UTC)


async def _site(db_session: AsyncSession, make_user, domain: str) -> Website:
    user = await make_user(sub=f"part-{domain}")
    workspace_id = await owner_workspace_id(db_session, user)
    site = Website(workspace_id=workspace_id, domain=domain, display_name=domain)
    db_session.add(site)
    await db_session.flush()
    return site


def _point(site: Website, day: date) -> MetricPoint:
    return MetricPoint(
        website_id=site.id, source="ga4", metric="sessions", dim_key="", day=day,
        value=1.0, dims={}, collected_at=NOW,
    )


async def _partition_of(db_session: AsyncSession, day: date) -> str:
    return await db_session.scalar(
        text("SELECT tableoid::regclass::text FROM metric_points WHERE day = :day"),
        {"day": day},
    )


def test_month_arithmetic_and_names() -> None:
    assert add_months(date(2026, 9, 1), 4) == date(2027, 1, 1)
    assert add_months(date(2026, 1, 1), -1) == date(2025, 12, 1)
    assert partition_name(date(2026, 9, 1)) == "metric_points_p2026_09"


async def test_ensure_partitions_creates_the_window_once(db_session: AsyncSession) -> None:
    created = await ensure_partitions(db_session, today=TODAY)
    assert created == [
        "metric_points_p2026_05",
        "metric_points_p2026_06",
        "metric_points_p2026_07",
        "metric_points_p2026_08",
        "metric_points_p2026_09",
        "metric_points_p2026_10",
        "metric_points_p2026_11",
        "metric_points_p2026_12",
    ]
    assert await ensure_partitions(db_session, today=TODAY) == []
    partitions = {p.name: p for p in await list_partitions(db_session)}
    assert partitions[DEFAULT_PARTITION].start is None
    assert partitions["metric_points_p2026_09"].start == date(2026, 9, 1)
    assert partitions["metric_points_p2026_09"].end == date(2026, 10, 1)


async def test_rows_waiting_in_the_default_partition_move_to_their_month(
    db_session: AsyncSession, make_user
) -> None:
    site = await _site(db_session, make_user, "part-move.test")
    db_session.add(_point(site, date(2027, 2, 10)))
    await db_session.flush()
    assert await _partition_of(db_session, date(2027, 2, 10)) == DEFAULT_PARTITION

    created = await ensure_partitions(db_session, today=TODAY, months_back=0, months_ahead=5)
    assert "metric_points_p2027_02" in created
    assert await _partition_of(db_session, date(2027, 2, 10)) == "metric_points_p2027_02"
    # Déplacée, pas copiée : une seule ligne au total.
    count = await db_session.scalar(
        select(func.count()).select_from(MetricPoint).where(MetricPoint.website_id == site.id)
    )
    assert count == 1


async def test_rows_of_other_months_stay_in_the_default_partition(
    db_session: AsyncSession, make_user
) -> None:
    site = await _site(db_session, make_user, "part-stay.test")
    db_session.add_all([_point(site, date(2027, 2, 10)), _point(site, date(2027, 4, 1))])
    await db_session.flush()

    await ensure_partitions(db_session, today=date(2027, 2, 5), months_back=0, months_ahead=0)
    assert await _partition_of(db_session, date(2027, 2, 10)) == "metric_points_p2027_02"
    assert await _partition_of(db_session, date(2027, 4, 1)) == DEFAULT_PARTITION


async def test_failed_partition_creation_leaves_no_orphan_table(
    db_session: AsyncSession,
) -> None:
    # Une partition chevauchante existe déjà : l'ATTACH du mois échoue, et la table
    # intermédiaire créée juste avant ne doit pas survivre.
    await db_session.execute(
        text(
            "CREATE TABLE metric_points_overlap PARTITION OF metric_points "
            "FOR VALUES FROM ('2026-09-15') TO ('2026-10-15')"
        )
    )
    with pytest.raises(DBAPIError):
        await ensure_partitions(db_session, today=TODAY, months_back=0, months_ahead=0)
    orphan = await db_session.scalar(text("SELECT to_regclass('metric_points_p2026_09')"))
    assert orphan is None
    # La session reste utilisable après l'échec.
    assert await db_session.scalar(text("SELECT 1")) == 1


async def test_purge_drops_expired_partitions_and_old_default_rows(
    db_session: AsyncSession, make_user
) -> None:
    site = await _site(db_session, make_user, "part-purge.test")
    await ensure_partitions(db_session, today=date(2024, 5, 10), months_back=0, months_ahead=0)
    db_session.add_all([_point(site, date(2024, 3, 15)), _point(site, date(2026, 9, 20))])
    await db_session.flush()

    result = await purge_expired(db_session, today=TODAY)
    assert result.dropped == ("metric_points_p2024_05",)
    assert result.deleted_default_rows == 1  # le 2024-03-15, plus vieux que 25 mois
    days = (
        await db_session.execute(select(MetricPoint.day).where(MetricPoint.website_id == site.id))
    ).scalars().all()
    assert days == [date(2026, 9, 20)]

    again = await purge_expired(db_session, today=TODAY)
    assert again.dropped == () and again.deleted_default_rows == 0


async def test_purge_keeps_everything_on_or_after_the_retention_boundary(
    db_session: AsyncSession, make_user
) -> None:
    # Au 2026-09-26 la limite est le 2024-08-01 : le mois 2024-07 (fin exclue le
    # 2024-08-01) est entièrement expiré, le mois 2024-08 contient encore des données.
    site = await _site(db_session, make_user, "part-boundary.test")
    await ensure_partitions(db_session, today=date(2024, 7, 10), months_back=0, months_ahead=1)
    db_session.add_all([
        _point(site, date(2024, 7, 31)),
        _point(site, date(2024, 8, 1)),
        _point(site, date(2024, 6, 30)),  # partition par défaut, avant la limite
        _point(site, date(2024, 9, 30)),  # partition par défaut, après la limite
    ])
    await db_session.flush()

    result = await purge_expired(db_session, today=TODAY)
    assert result.dropped == ("metric_points_p2024_07",)
    assert result.deleted_default_rows == 1
    days = (
        await db_session.execute(
            select(MetricPoint.day).where(MetricPoint.website_id == site.id).order_by(MetricPoint.day)
        )
    ).scalars().all()
    assert days == [date(2024, 8, 1), date(2024, 9, 30)]
    names = {p.name for p in await list_partitions(db_session)}
    assert "metric_points_p2024_08" in names and "metric_points_p2024_07" not in names


async def test_purge_never_touches_the_current_window(db_session: AsyncSession) -> None:
    await ensure_partitions(db_session, today=TODAY)
    result = await purge_expired(db_session, today=TODAY)
    assert result.dropped == () and result.deleted_default_rows == 0
    assert "metric_points_p2026_09" in {p.name for p in await list_partitions(db_session)}


async def test_lock_timeout_is_set_for_the_transaction(db_session: AsyncSession) -> None:
    await ensure_partitions(db_session, today=TODAY, months_back=0, months_ahead=0)
    assert await db_session.scalar(text("SHOW lock_timeout")) == "5s"
    await db_session.execute(text("SET LOCAL lock_timeout = 0"))
    await purge_expired(db_session, today=TODAY)
    assert await db_session.scalar(text("SHOW lock_timeout")) == "5s"


async def test_purge_ignores_foreign_partition_names_and_purges_the_rest(
    db_session: AsyncSession,
) -> None:
    await db_session.execute(
        text(
            "CREATE TABLE metric_points_foreign_old PARTITION OF metric_points "
            "FOR VALUES FROM ('2020-01-01') TO ('2020-02-01')"
        )
    )
    await ensure_partitions(db_session, today=date(2024, 5, 10), months_back=0, months_ahead=0)

    result = await purge_expired(db_session, today=TODAY)
    assert result.dropped == ("metric_points_p2024_05",)
    assert result.unexpected == ("metric_points_foreign_old",)
    names = {p.name for p in await list_partitions(db_session)}
    assert "metric_points_foreign_old" in names


async def test_unrecognised_bound_is_never_default_nor_purged(db_session: AsyncSession) -> None:
    await db_session.execute(
        text(
            "CREATE TABLE metric_points_pmin PARTITION OF metric_points "
            "FOR VALUES FROM (MINVALUE) TO ('2020-01-01')"
        )
    )
    by_name = {p.name: p for p in await list_partitions(db_session)}
    assert by_name["metric_points_pmin"].kind == "unknown"
    assert by_name[DEFAULT_PARTITION].kind == "default"

    result = await purge_expired(db_session, today=TODAY)
    assert result.dropped == ()
    assert "metric_points_pmin" in result.unexpected
    assert "metric_points_pmin" in {p.name for p in await list_partitions(db_session)}


async def test_parameters_are_validated(db_session: AsyncSession) -> None:
    with pytest.raises(ValueError):
        await purge_expired(db_session, today=TODAY, retention_months=0)
    with pytest.raises(ValueError):
        await purge_expired(db_session, today=TODAY, retention_months=-3)
    with pytest.raises(ValueError):
        await ensure_partitions(db_session, today=TODAY, months_back=-1)
    with pytest.raises(ValueError):
        await ensure_partitions(db_session, today=TODAY, months_ahead=-1)


async def test_purge_boundary_first_day_versus_last_day_of_month(
    db_session: AsyncSession,
) -> None:
    await ensure_partitions(db_session, today=date(2024, 6, 10), months_back=0, months_ahead=1)
    # Le 2026-08-31 la limite est le 2024-07-01 : seul juin 2024 est entièrement expiré.
    last_day = await purge_expired(db_session, today=date(2026, 8, 31))
    assert last_day.dropped == ("metric_points_p2024_06",)
    # Le 2026-09-01 la limite passe au 2024-08-01 : juillet 2024 est expiré à son tour.
    first_day = await purge_expired(db_session, today=date(2026, 9, 1))
    assert first_day.dropped == ("metric_points_p2024_07",)


async def test_purge_boundary_across_a_year_change(db_session: AsyncSession) -> None:
    await ensure_partitions(db_session, today=date(2024, 11, 5), months_back=0, months_ahead=1)
    # Le 2027-01-15 la limite est le 2024-12-01 : novembre 2024 est expiré, pas décembre.
    result = await purge_expired(db_session, today=date(2027, 1, 15))
    assert result.dropped == ("metric_points_p2024_11",)
    assert "metric_points_p2024_12" in {p.name for p in await list_partitions(db_session)}


async def test_default_partition_row_exactly_on_the_cutoff_is_kept(
    db_session: AsyncSession, make_user
) -> None:
    site = await _site(db_session, make_user, "part-cutoff.test")
    # Limite au 2026-09-26 : 2024-08-01. La veille est supprimée, le jour même conservé.
    db_session.add_all([_point(site, date(2024, 7, 31)), _point(site, date(2024, 8, 1))])
    await db_session.flush()

    result = await purge_expired(db_session, today=TODAY)
    assert result.deleted_default_rows == 1
    days = (
        await db_session.execute(select(MetricPoint.day).where(MetricPoint.website_id == site.id))
    ).scalars().all()
    assert days == [date(2024, 8, 1)]
