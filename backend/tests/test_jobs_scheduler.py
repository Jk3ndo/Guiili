import asyncio
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.job_run import JobRun
from app.models.schedule import Schedule
from app.models.user import User
from app.models.website import Website
from app.models.workspace import Workspace
from app.models.workspace_member import WorkspaceMember
from app.services.jobs.health import report_jobs_health
from app.services.jobs.kinds import RunSpec
from app.services.jobs.queue import InlineQueue, TaskMessage
from app.services.jobs.scheduler import (
    due_schedules,
    expire_stale_queued,
    materialize_default_schedules,
    plan_run,
    tick,
)
from tests.jobs_fakes import RecordingQueue, make_site

NOW = datetime(2026, 9, 26, 6, 7, tzinfo=UTC)


async def _tick(session: AsyncSession, queue, *, now: datetime = NOW, daily_cap: int = 300):
    return await tick(session, queue, now=now, batch=100, daily_cap=daily_cap, max_attempts=5)


async def _schedules(session: AsyncSession, website_id) -> dict[str, Schedule]:
    rows = await session.execute(select(Schedule).where(Schedule.website_id == website_id))
    return {row.kind: row for row in rows.scalars()}


async def test_default_schedules_are_materialized_once_for_active_sites(
    db_session: AsyncSession, make_user
) -> None:
    site = await make_site(db_session, make_user, "tick-mat.test")
    archived = await make_site(db_session, make_user, "tick-archived.test")
    archived.archived_at = NOW
    await db_session.flush()

    assert await materialize_default_schedules(db_session, now=NOW) == 5
    assert await materialize_default_schedules(db_session, now=NOW) == 0
    schedules = await _schedules(db_session, site.id)
    assert {kind: s.frequency for kind, s in schedules.items()} == {
        "collect_ga4": "daily",
        "collect_gsc": "daily",
        "collect_cwv": "daily",
        "collect_probes": "three_daily",
        "measurement_check": "daily",
    }
    assert all(s.enabled and s.next_due_at == NOW for s in schedules.values())
    assert await _schedules(db_session, archived.id) == {}


async def test_a_first_tick_backfills_google_sources_and_runs_the_others(
    db_session: AsyncSession, make_user
) -> None:
    site = await make_site(db_session, make_user, "tick-first.test")
    queue = RecordingQueue()
    result = await _tick(db_session, queue)
    by_kind = {(m.spec.kind, m.spec.params.get("source")): m for m in queue.messages}
    assert set(by_kind) == {
        ("backfill", "ga4"),
        ("backfill", "gsc"),
        ("collect_cwv", None),
        ("collect_probes", None),
        ("measurement_check", None),
        ("partition_maintenance", None),
    }
    assert by_kind[("backfill", "ga4")].queue == "ga4"
    assert by_kind[("backfill", "gsc")].spec.window == "gsc-20260926T0000"
    assert by_kind[("collect_probes", None)].queue == "light"
    assert by_kind[("collect_cwv", None)].spec.key == f"collect_cwv:{site.id}:20260926T0000"
    assert by_kind[("partition_maintenance", None)].spec.key == "partition_maintenance:global:20260926"
    assert (result.materialized, result.enqueued, result.capped) == (5, 6, 0)

    schedules = await _schedules(db_session, site.id)
    assert schedules["collect_cwv"].next_due_at == datetime(2026, 9, 27, tzinfo=UTC)
    assert schedules["collect_probes"].next_due_at == datetime(2026, 9, 26, 8, tzinfo=UTC)
    queued = await db_session.scalar(
        select(func.count()).select_from(JobRun).where(JobRun.status == "queued")
    )
    assert queued == 6


async def test_a_second_tick_in_the_same_slot_deposits_nothing(
    db_session: AsyncSession, make_user
) -> None:
    await make_site(db_session, make_user, "tick-again.test")
    await _tick(db_session, RecordingQueue())
    queue = RecordingQueue()
    result = await _tick(db_session, queue, now=NOW + timedelta(minutes=15))
    assert queue.messages == [] and result.enqueued == 0


async def test_the_frequency_floor_applies_even_to_a_bad_row(
    db_session: AsyncSession, make_user
) -> None:
    site = await make_site(db_session, make_user, "tick-floor.test")
    db_session.add(
        Schedule(
            website_id=site.id, kind="collect_ga4", frequency="hourly", enabled=True,
            next_due_at=NOW, backfill_done_at=NOW - timedelta(days=1),
        )
    )
    await db_session.flush()
    queue = RecordingQueue()
    await _tick(db_session, queue)
    ga4 = next(m for m in queue.messages if m.spec.kind == "collect_ga4")
    assert ga4.spec.window == "20260926T0000"  # créneau de 8 h, pas d'1 h
    schedules = await _schedules(db_session, site.id)
    assert schedules["collect_ga4"].next_due_at == datetime(2026, 9, 26, 8, tzinfo=UTC)


async def test_the_workspace_daily_cap_holds_back_extra_tasks(
    db_session: AsyncSession, make_user
) -> None:
    site = await make_site(db_session, make_user, "tick-cap.test")
    queue = RecordingQueue()
    result = await _tick(db_session, queue, daily_cap=2)
    site_messages = [m for m in queue.messages if m.spec.website_id == site.id]
    assert len(site_messages) == 2 and result.capped == 3
    # Les plannings retenus restent dus : ils partiront le lendemain.
    schedules = await _schedules(db_session, site.id)
    assert sum(1 for s in schedules.values() if s.next_due_at == NOW) == 3


async def test_a_failed_deposit_is_retried_at_the_next_tick(
    db_session: AsyncSession, make_user
) -> None:
    site = await make_site(db_session, make_user, "tick-enqueue-fail.test")
    result = await _tick(db_session, RecordingQueue(failing_kinds=frozenset({"collect_cwv"})))
    assert result.failed_enqueue == 1
    schedules = await _schedules(db_session, site.id)
    assert schedules["collect_cwv"].next_due_at == NOW  # redevenu dû
    run = await db_session.scalar(select(JobRun).where(JobRun.kind == "collect_cwv"))
    assert (run.status, run.error_code) == ("failed", "enqueue_failed")

    queue = RecordingQueue()
    await _tick(db_session, queue, now=NOW + timedelta(minutes=15))
    assert [m.spec.kind for m in queue.messages] == ["collect_cwv"]
    await db_session.refresh(run)
    assert run.status == "queued" and run.error_code is None


async def test_archived_sites_and_disabled_schedules_are_not_due(
    db_session: AsyncSession, make_user
) -> None:
    site = await make_site(db_session, make_user, "tick-disabled.test")
    db_session.add(
        Schedule(website_id=site.id, kind="collect_cwv", frequency="daily", enabled=False,
                 next_due_at=NOW - timedelta(days=1))
    )
    await db_session.flush()
    assert await due_schedules(db_session, now=NOW, limit=10) == []


async def test_stale_queued_runs_expire(db_session: AsyncSession, make_user) -> None:
    site = await make_site(db_session, make_user, "tick-expire.test")
    db_session.add(
        JobRun(
            idempotency_key="old", kind="collect_probes", website_id=site.id,
            workspace_id=site.workspace_id, window_label="w", params={}, status="queued",
            attempt=0, max_attempts=5, observations=0, enqueued_at=NOW - timedelta(hours=3),
        )
    )
    await db_session.flush()
    assert await expire_stale_queued(db_session, now=NOW) == 1
    run = await db_session.scalar(select(JobRun).where(JobRun.idempotency_key == "old"))
    await db_session.refresh(run)
    assert (run.status, run.error_code, run.recoverable) == ("failed", "not_dispatched", True)


async def test_plan_run_switches_to_regular_collection_after_the_backfill(
    db_session: AsyncSession, make_user
) -> None:
    site = await make_site(db_session, make_user, "tick-plan.test")
    schedule = Schedule(website_id=site.id, kind="collect_gsc", frequency="daily",
                        enabled=True, next_due_at=NOW)
    assert plan_run(schedule, site, now=NOW) == RunSpec(
        "backfill", site.id, site.workspace_id, "gsc-20260926T0000", {"source": "gsc"}
    )
    schedule.backfill_done_at = NOW
    assert plan_run(schedule, site, now=NOW) == RunSpec(
        "collect_gsc", site.id, site.workspace_id, "20260926T0000"
    )


async def test_inline_queue_executes_in_process() -> None:
    seen: list[str] = []

    async def execute(spec: RunSpec) -> None:
        seen.append(spec.key)

    queue = InlineQueue(execute)
    spec = RunSpec("partition_maintenance", None, None, "20260926")
    await queue.enqueue(TaskMessage(spec, spec.queue))
    assert seen == queue.executed == ["partition_maintenance:global:20260926"]


async def test_a_key_already_queued_or_finished_is_not_deposited_again(
    db_session: AsyncSession, make_user
) -> None:
    site = await make_site(db_session, make_user, "tick-idem.test")
    key = f"collect_cwv:{site.id}:20260926T0000"
    db_session.add(
        JobRun(
            idempotency_key=key, kind="collect_cwv", website_id=site.id,
            workspace_id=site.workspace_id, window_label="20260926T0000", params={},
            status="running", attempt=1, max_attempts=5, observations=0, enqueued_at=NOW,
        )
    )
    await db_session.flush()
    queue = RecordingQueue()
    await _tick(db_session, queue)
    assert all(m.spec.key != key for m in queue.messages)
    # Le planning avance quand même : pas de ré-enfilage en boucle au passage suivant.
    schedules = await _schedules(db_session, site.id)
    assert schedules["collect_cwv"].next_due_at == datetime(2026, 9, 27, tzinfo=UTC)
    run = await db_session.scalar(select(JobRun).where(JobRun.idempotency_key == key))
    assert run.status == "running"


async def test_a_deposit_failing_with_an_unexpected_error_does_not_lose_the_others(
    db_session: AsyncSession, make_user
) -> None:
    site = await make_site(db_session, make_user, "tick-boom.test")

    class Exploding(RecordingQueue):
        async def enqueue(self, message: TaskMessage) -> None:
            if message.spec.kind == "collect_cwv":
                raise RuntimeError("secret-token-in-url")
            await super().enqueue(message)

    queue = Exploding()
    result = await _tick(db_session, queue)
    assert result.failed_enqueue == 1 and result.enqueued == 5
    schedules = await _schedules(db_session, site.id)
    assert schedules["collect_cwv"].next_due_at == NOW


async def test_a_failing_inline_task_does_not_break_the_tick(
    db_session: AsyncSession, make_user
) -> None:
    await make_site(db_session, make_user, "tick-inline-fail.test")

    async def execute(spec: RunSpec) -> None:
        raise RuntimeError("boom")

    queue = InlineQueue(execute)
    result = await _tick(db_session, queue)
    assert result.enqueued == 6 and result.failed_enqueue == 0
    assert len(queue.executed) == 6


async def test_the_health_report_runs_with_the_injected_clock_and_never_breaks_the_tick(
    db_session: AsyncSession, make_user, monkeypatch
) -> None:
    site = await make_site(db_session, make_user, "tick-health.test")
    db_session.add(
        Schedule(
            website_id=site.id, kind="collect_ga4", frequency="daily", enabled=True,
            next_due_at=NOW + timedelta(days=1), backfill_done_at=NOW,
            failing_since=NOW - timedelta(days=2), last_error_code="api_error",
        )
    )
    await db_session.flush()
    reported: list[datetime] = []
    real_report = report_jobs_health

    def capture(message, extra):
        raise RuntimeError("sentry down")

    def spy(health, **kwargs):
        reported.append(health.checked_at)
        real_report(health, capture=capture)

    monkeypatch.setattr("app.services.jobs.scheduler.report_jobs_health", spy)
    result = await _tick(db_session, RecordingQueue())
    assert reported == [NOW] and result.enqueued == 5


async def test_concurrent_ticks_never_take_the_same_schedule(engine) -> None:
    maker = async_sessionmaker(bind=engine, expire_on_commit=False)
    async with maker() as setup:
        user = User(email="tick-lock@example.com", google_sub="tick-lock-sub")
        setup.add(user)
        await setup.flush()
        workspace = Workspace(name="tick-lock", owner_user_id=user.id)
        setup.add(workspace)
        await setup.flush()
        setup.add(WorkspaceMember(workspace_id=workspace.id, user_id=user.id, role="owner"))
        site = Website(workspace_id=workspace.id, domain="tick-lock.test", display_name="lock")
        setup.add(site)
        await setup.flush()
        await materialize_default_schedules(setup, now=NOW)
        await setup.commit()
        site_id, workspace_id, user_id = site.id, workspace.id, user.id

    try:
        async with maker() as first, maker() as second:
            mine = [s.id for s, _ in await due_schedules(first, now=NOW, limit=2)]
            assert len(mine) == 2  # verrous de lignes tenus par la première transaction
            # SKIP LOCKED : la seconde passe ne bloque pas (aucun verrou en attente) et
            # reçoit exactement les plannings restants.
            others = [
                s.id
                for s, _ in await asyncio.wait_for(
                    due_schedules(second, now=NOW, limit=10), timeout=10
                )
                if s.website_id == site_id
            ]
            waiting = await second.scalar(text("SELECT count(*) FROM pg_locks WHERE NOT granted"))
            assert waiting == 0
            assert len(others) == 3 and not set(mine) & set(others)
            await first.rollback()
            await second.rollback()
    finally:
        async with maker() as cleanup:
            await cleanup.execute(delete(Website).where(Website.id == site_id))
            await cleanup.execute(delete(Workspace).where(Workspace.id == workspace_id))
            await cleanup.execute(delete(User).where(User.id == user_id))
            await cleanup.commit()
