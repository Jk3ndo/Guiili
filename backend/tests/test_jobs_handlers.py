from datetime import date, timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.job_run import JobRun
from app.models.measurement_item_status import MeasurementItemStatus
from app.models.metric_point import MetricPoint
from app.models.schedule import Schedule
from app.services.jobs import handlers as handlers_module
from app.services.jobs.handlers import (
    JobServices,
    build_handlers,
    purge_old_job_runs,
    quota_breaker_open,
)
from app.services.jobs.kinds import KINDS, RunSpec
from app.services.jobs.runner import execute_run
from app.services.metrics.partitions import PurgeResult, list_partitions
from app.services.metrics.sources import factory as factory_module
from app.services.metrics.sources.credentials import GoogleCredentials
from app.services.metrics.sources.cwv import CwvSource
from app.services.metrics.sources.factory import default_source_factory
from app.services.metrics.sources.probes import ProbeSource
from app.services.metrics.types import DayRange, Observation, SourceError
from tests.jobs_fakes import (
    LIMITS,
    NOW,
    TODAY,
    FakeSource,
    fake_services,
    make_site,
    offline_fetcher,
    unlinked_reader_factory,
)


def _clock():
    return NOW


def _today():
    return TODAY


def test_every_kind_has_a_handler() -> None:
    assert set(build_handlers(fake_services({}))) == set(KINDS)


async def test_collect_stores_the_regular_window_with_the_run_id(
    db_session: AsyncSession, make_user
) -> None:
    site = await make_site(db_session, make_user, "h-collect.test")
    ga4 = FakeSource("ga4", [Observation("sessions", date(2026, 9, 24), 12.0),
                             Observation("sessions", date(2026, 6, 1), 99.0)])
    handlers = build_handlers(fake_services({"ga4": ga4}))
    spec = RunSpec("collect_ga4", site.id, site.workspace_id, "20260926T0000")
    result = await execute_run(db_session, spec, handlers=handlers, limits=LIMITS, clock=_clock)
    assert result.status == "succeeded"
    assert ga4.calls == [DayRange(date(2026, 9, 23), date(2026, 9, 25))]
    point = await db_session.scalar(select(MetricPoint).where(MetricPoint.website_id == site.id))
    run = await db_session.scalar(select(JobRun).where(JobRun.idempotency_key == spec.key))
    assert (point.day, point.value, point.run_id) == (date(2026, 9, 24), 12.0, run.id)
    assert run.observations == 1


async def test_backfill_collects_90_days_in_chunks_and_marks_the_schedule(
    db_session: AsyncSession, make_user
) -> None:
    site = await make_site(db_session, make_user, "h-backfill.test")
    db_session.add(Schedule(website_id=site.id, kind="collect_gsc", frequency="daily",
                            enabled=True, next_due_at=NOW))
    await db_session.flush()
    gsc = FakeSource("gsc", [Observation("clicks", date(2026, 7, 1), 3.0)])
    spec = RunSpec("backfill", site.id, site.workspace_id, "gsc-20260926T0000", {"source": "gsc"})
    result = await execute_run(
        db_session, spec, handlers=build_handlers(fake_services({"gsc": gsc})), limits=LIMITS,
        clock=_clock,
    )
    assert result.status == "succeeded"
    assert [c.length for c in gsc.calls] == [31, 31, 28]
    assert gsc.calls[-1].end == date(2026, 9, 23)
    schedule = await db_session.scalar(select(Schedule).where(Schedule.website_id == site.id))
    assert schedule.backfill_done_at == NOW


async def test_an_unlinked_source_is_skipped(db_session: AsyncSession, make_user) -> None:
    site = await make_site(db_session, make_user, "h-unlinked.test")
    ga4 = FakeSource(
        "ga4", error=SourceError("ga4_not_connected", recoverable=False, not_applicable=True)
    )
    spec = RunSpec("collect_ga4", site.id, site.workspace_id, "w")
    result = await execute_run(
        db_session, spec, handlers=build_handlers(fake_services({"ga4": ga4})), limits=LIMITS,
        clock=_clock,
    )
    assert (result.status, result.retry) == ("skipped", False)


async def test_an_archived_site_is_skipped_without_collecting(
    db_session: AsyncSession, make_user
) -> None:
    site = await make_site(db_session, make_user, "h-archived.test")
    site.archived_at = NOW
    await db_session.flush()
    calls: list[str] = []
    spec = RunSpec("collect_probes", site.id, site.workspace_id, "w")
    result = await execute_run(
        db_session, spec, handlers=build_handlers(fake_services({}, calls)), limits=LIMITS,
        clock=_clock,
    )
    assert result.status == "skipped" and calls == []


async def test_repeated_quota_errors_open_the_breaker(db_session: AsyncSession, make_user) -> None:
    site = await make_site(db_session, make_user, "h-breaker.test")
    for index in range(3):
        db_session.add(
            JobRun(
                idempotency_key=f"q{index}", kind="collect_ga4", website_id=site.id,
                workspace_id=site.workspace_id, window_label="w", params={}, status="failed",
                error_code="quota", recoverable=True, attempt=1, max_attempts=5,
                observations=0, finished_at=NOW - timedelta(minutes=10),
            )
        )
    await db_session.flush()
    assert await quota_breaker_open(db_session, workspace_id=site.workspace_id, source="ga4", now=NOW)
    assert not await quota_breaker_open(
        db_session, workspace_id=site.workspace_id, source="gsc", now=NOW
    )
    calls: list[str] = []
    spec = RunSpec("collect_ga4", site.id, site.workspace_id, "breaker")
    result = await execute_run(
        db_session, spec, handlers=build_handlers(fake_services({}, calls)), limits=LIMITS,
        clock=_clock,
    )
    assert (result.status, result.retry) == ("failed", True)
    run = await db_session.scalar(select(JobRun).where(JobRun.idempotency_key == spec.key))
    assert run.error_code == "circuit_open" and calls == []


async def test_the_breaker_counts_backfill_runs_and_reopens_after_the_window(
    db_session: AsyncSession, make_user
) -> None:
    site = await make_site(db_session, make_user, "h-breaker2.test")
    for index, age in enumerate((5, 10, 40)):
        db_session.add(
            JobRun(
                idempotency_key=f"b{index}", kind="backfill", website_id=site.id,
                workspace_id=site.workspace_id, window_label="w", params={"source": "gsc"},
                status="failed", error_code="quota", recoverable=True, attempt=1, max_attempts=5,
                observations=0, finished_at=NOW - timedelta(minutes=age),
            )
        )
    await db_session.flush()
    # 2 échecs dans la fenêtre de 30 minutes seulement : le disjoncteur reste fermé.
    assert not await quota_breaker_open(
        db_session, workspace_id=site.workspace_id, source="gsc", now=NOW
    )
    db_session.add(
        JobRun(
            idempotency_key="b3", kind="collect_gsc", website_id=site.id,
            workspace_id=site.workspace_id, window_label="w", params={}, status="failed",
            error_code="quota", recoverable=True, attempt=1, max_attempts=5, observations=0,
            finished_at=NOW - timedelta(minutes=1),
        )
    )
    await db_session.flush()
    assert await quota_breaker_open(
        db_session, workspace_id=site.workspace_id, source="gsc", now=NOW
    )
    assert not await quota_breaker_open(
        db_session, workspace_id=site.workspace_id, source="gsc", now=NOW + timedelta(minutes=40)
    )


async def test_the_scheduled_plan_check_never_launches_a_browser(
    db_session: AsyncSession, make_user
) -> None:
    site = await make_site(db_session, make_user, "h-plan.test")
    spec = RunSpec("measurement_check", site.id, site.workspace_id, "w")
    result = await execute_run(
        db_session, spec, handlers=build_handlers(fake_services({})), limits=LIMITS, clock=_clock
    )
    assert result.status == "succeeded"
    statuses = await db_session.scalar(
        select(func.count())
        .select_from(MeasurementItemStatus)
        .where(MeasurementItemStatus.website_id == site.id)
    )
    assert statuses > 0


async def test_partition_maintenance_creates_months_and_purges_old_runs(
    db_session: AsyncSession, make_user
) -> None:
    site = await make_site(db_session, make_user, "h-maint.test")
    db_session.add(
        JobRun(
            idempotency_key="ancienne", kind="collect_probes", website_id=site.id,
            workspace_id=site.workspace_id, window_label="w", params={}, status="succeeded",
            attempt=1, max_attempts=5, observations=0, finished_at=NOW - timedelta(days=91),
        )
    )
    await db_session.flush()
    spec = RunSpec("partition_maintenance", None, None, "20260926")
    result = await execute_run(
        db_session, spec, handlers=build_handlers(fake_services({})), limits=LIMITS, clock=_clock
    )
    assert result.status == "succeeded"
    names = {p.name for p in await list_partitions(db_session)}
    assert {"metric_points_p2026_09", "metric_points_p2026_12"} <= names
    assert await db_session.scalar(
        select(func.count()).select_from(JobRun).where(JobRun.idempotency_key == "ancienne")
    ) == 0


async def test_purge_old_job_runs_keeps_unfinished_and_recent_runs(
    db_session: AsyncSession, make_user
) -> None:
    site = await make_site(db_session, make_user, "h-purge.test")
    for key, finished in (("vieux", NOW - timedelta(days=100)), ("recent", NOW), ("encours", None)):
        db_session.add(
            JobRun(
                idempotency_key=key, kind="collect_probes", website_id=site.id,
                workspace_id=site.workspace_id, window_label="w", params={},
                status="running" if finished is None else "succeeded", attempt=1,
                max_attempts=5, observations=0, finished_at=finished,
            )
        )
    await db_session.flush()
    assert await purge_old_job_runs(db_session, now=NOW) == 1


async def test_default_factory_builds_the_light_sources() -> None:
    async def tls(domain):
        raise AssertionError("aucun appel attendu")

    factory = default_source_factory(
        pagespeed_api_key=None, oauth=None, cipher=None, tls_checker=tls, page_fetcher=offline_fetcher
    )
    assert isinstance(await factory(None, None, "cwv"), CwvSource)
    assert isinstance(await factory(None, None, "probe"), ProbeSource)
    with pytest.raises(SourceError) as excinfo:
        await factory(None, None, "inconnue")
    assert excinfo.value.reason == "unknown_source" and not excinfo.value.recoverable


# -- points reportés des relectures précédentes --------------------------------------


async def test_a_factory_error_still_commits_and_is_classified(
    db_session: AsyncSession, make_user, monkeypatch
) -> None:
    """La fabrique peut avoir passé une connexion à `needs_reauth` avant d'échouer : ces
    effets sont committés avant la propagation (`execute_run` fait `rollback`)."""
    site = await make_site(db_session, make_user, "h-commit.test")
    events: list[str] = []
    real_commit = db_session.commit

    async def tracking_commit() -> None:
        events.append("commit")
        await real_commit()

    async def factory(session, website, name):
        events.append("factory")
        raise SourceError("token_unavailable", recoverable=False)

    monkeypatch.setattr(db_session, "commit", tracking_commit)
    services = JobServices(
        source_factory=factory, page_fetcher=offline_fetcher,
        reader_factory=unlinked_reader_factory, today=_today, now=_clock,
    )
    spec = RunSpec("collect_gsc", site.id, site.workspace_id, "w")
    result = await execute_run(
        db_session, spec, handlers=build_handlers(services), limits=LIMITS, clock=_clock
    )
    assert (result.status, result.retry) == ("failed", False)
    # réclamation, fabrique, commit des effets de la fabrique, clôture
    assert events == ["commit", "factory", "commit", "commit"]


async def test_the_google_factory_passes_the_token_problem(monkeypatch) -> None:
    async def fake_resolve(session, website, *, oauth, cipher):
        return GoogleCredentials(
            ga4_property="properties/1", ga4_token=None, gsc_site="sc-domain:x.test",
            gsc_token=None, ga4_problem="token_refresh_failed", gsc_problem="token_unavailable",
        )

    monkeypatch.setattr(factory_module, "resolve_google_credentials", fake_resolve)
    factory = default_source_factory(
        pagespeed_api_key=None, oauth=None, cipher=None, tls_checker=None,
        page_fetcher=offline_fetcher,
    )
    window = DayRange(date(2026, 9, 1), date(2026, 9, 2))
    with pytest.raises(SourceError) as ga4_error:
        await (await factory(None, None, "ga4")).collect(None, window)
    with pytest.raises(SourceError) as gsc_error:
        await (await factory(None, None, "gsc")).collect(None, window)
    assert (ga4_error.value.reason, ga4_error.value.recoverable) == ("token_refresh_failed", True)
    assert (gsc_error.value.reason, gsc_error.value.recoverable) == ("token_unavailable", False)


async def test_the_factory_gives_the_injected_date_to_the_light_sources() -> None:
    factory = default_source_factory(
        pagespeed_api_key=None, oauth=None, cipher=None, tls_checker=None,
        page_fetcher=offline_fetcher, today=lambda: date(2026, 9, 26),
    )
    probe = await factory(None, None, "probe")
    cwv = await factory(None, None, "cwv")
    assert probe._today() == date(2026, 9, 26)
    assert cwv._today() == date(2026, 9, 26)


async def test_backfill_rejects_a_source_without_history(
    db_session: AsyncSession, make_user
) -> None:
    site = await make_site(db_session, make_user, "h-badparams.test")
    spec = RunSpec("backfill", site.id, site.workspace_id, "cwv-w", {"source": "cwv"})
    result = await execute_run(
        db_session, spec, handlers=build_handlers(fake_services({})), limits=LIMITS, clock=_clock
    )
    assert (result.status, result.retry) == ("failed", False)


async def test_a_partial_probe_is_flagged_on_the_run(db_session: AsyncSession, make_user) -> None:
    site = await make_site(db_session, make_user, "h-partial.test")
    probe = FakeSource("probe", [Observation("page_up", NOW.date(), 1.0)])
    spec = RunSpec("collect_probes", site.id, site.workspace_id, "w")
    result = await execute_run(
        db_session, spec, handlers=build_handlers(fake_services({"probe": probe})),
        limits=LIMITS, clock=_clock,
    )
    assert result.status == "succeeded"
    run = await db_session.scalar(select(JobRun).where(JobRun.idempotency_key == spec.key))
    assert run.error_code == "probe_partial"


async def test_a_complete_probe_is_not_flagged(db_session: AsyncSession, make_user) -> None:
    site = await make_site(db_session, make_user, "h-complete.test")
    probe = FakeSource(
        "probe",
        [Observation("page_up", NOW.date(), 1.0), Observation("tls_days_remaining", NOW.date(), 60.0)],
    )
    spec = RunSpec("collect_probes", site.id, site.workspace_id, "w")
    await execute_run(
        db_session, spec, handlers=build_handlers(fake_services({"probe": probe})),
        limits=LIMITS, clock=_clock,
    )
    run = await db_session.scalar(select(JobRun).where(JobRun.idempotency_key == spec.key))
    assert (run.status, run.error_code) == ("succeeded", None)


async def test_maintenance_commits_creation_before_purge_and_fails_on_unexpected_partitions(
    db_session: AsyncSession, monkeypatch
) -> None:
    events: list[str] = []
    real_commit = db_session.commit

    async def tracking_commit() -> None:
        events.append("commit")
        await real_commit()

    async def fake_ensure(session, *, today):
        events.append("ensure")
        return []

    async def fake_purge(session, *, today):
        events.append("purge")
        return PurgeResult(dropped=(), deleted_default_rows=0, unexpected=("metric_points_bizarre",))

    monkeypatch.setattr(db_session, "commit", tracking_commit)
    monkeypatch.setattr(handlers_module, "ensure_partitions", fake_ensure)
    monkeypatch.setattr(handlers_module, "purge_expired", fake_purge)
    spec = RunSpec("partition_maintenance", None, None, "20260927")
    result = await execute_run(
        db_session, spec, handlers=build_handlers(fake_services({})), limits=LIMITS, clock=_clock
    )
    assert (result.status, result.retry) == ("failed", False)
    run = await db_session.scalar(select(JobRun).where(JobRun.idempotency_key == spec.key))
    assert run.error_code == "unexpected_partitions"
    # réclamation ; création puis commit ; purge puis commit ; clôture
    assert events == ["commit", "ensure", "commit", "purge", "commit", "commit"]
