import asyncio
import logging
from datetime import UTC, datetime, timedelta, timezone

from sqlalchemy import delete, func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.job_run import JobRun
from app.models.schedule import Schedule
from app.models.user import User
from app.models.website import Website
from app.models.workspace import Workspace
from app.models.workspace_member import WorkspaceMember
from app.services.jobs.health import STUCK_RUNNING_GRACE, compute_jobs_health, report_jobs_health
from app.services.jobs.kinds import RunSpec
from app.services.jobs.queue import EnqueueError, InlineQueue, TaskMessage
from app.services.jobs.runner import lock_key
from app.services.jobs.scheduler import (
    STUCK_RUNNING_SWEEP_AFTER,
    TICK_LOCK_KEY,
    due_schedules,
    expire_stale_queued,
    expire_stuck_running,
    materialize_default_schedules,
    plan_run,
    runs_today,
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
    db_session: AsyncSession, make_user, caplog
) -> None:
    site = await make_site(db_session, make_user, "tick-cap.test")
    queue = RecordingQueue()
    with caplog.at_level(logging.WARNING, logger="app.services.jobs.scheduler"):
        result = await _tick(db_session, queue, daily_cap=2)
    site_messages = [m for m in queue.messages if m.spec.website_id == site.id]
    assert len(site_messages) == 2 and result.capped == 3
    # Écart au brief : les plannings retenus AVANCENT aussi (au plus tard à minuit UTC),
    # sinon ils seraient re-sélectionnés en tête de chaque passage et compteraient
    # « en retard ». Sondes 8 h : créneau suivant ; les autres : minuit.
    schedules = await _schedules(db_session, site.id)
    midnight = datetime(2026, 9, 27, tzinfo=UTC)
    assert {kind: s.next_due_at for kind, s in schedules.items()} == {
        "collect_ga4": midnight,
        "collect_gsc": midnight,
        "collect_cwv": midnight,
        "collect_probes": datetime(2026, 9, 26, 8, tzinfo=UTC),
        "measurement_check": midnight,
    }
    records = [r for r in caplog.records if getattr(r, "event", "") == "job_daily_cap_reached"]
    assert [(r.workspace_id, r.held) for r in records] == [(str(site.workspace_id), 3)]


async def test_held_schedules_beyond_the_batch_do_not_starve_another_workspace(
    db_session: AsyncSession, make_user
) -> None:
    big_a = await make_site(db_session, make_user, "tick-big-a.test")
    big_b = await make_site(db_session, make_user, "tick-big-b.test")
    other = await make_site(db_session, make_user, "tick-other.test")
    # Le workspace « gros » : 2 sites dans le même workspace.
    big_b.workspace_id = big_a.workspace_id
    await db_session.flush()
    await materialize_default_schedules(db_session, now=NOW)
    for schedule in (await db_session.scalars(select(Schedule))).all():
        if schedule.website_id in (big_a.id, big_b.id):
            schedule.next_due_at = NOW - timedelta(days=1)  # les plus anciens : en tête du lot
    await db_session.flush()

    queue = RecordingQueue()
    kwargs = {"now": NOW, "batch": 6, "daily_cap": 1, "max_attempts": 5}
    first = await tick(db_session, queue, **kwargs)
    assert first.enqueued == 2 and first.capped == 5  # 1 tâche du gros + la maintenance
    second = await tick(db_session, queue, **kwargs)
    # Les 10 plannings retenus dépassent le lot (6) mais ont avancé : le second passage
    # atteint l'autre workspace.
    website_ids = [m.spec.website_id for m in queue.messages]
    assert website_ids.count(other.id) == 1
    assert website_ids.count(big_a.id) + website_ids.count(big_b.id) == 1
    assert second.capped >= 4
    big = [
        s for s in (await db_session.scalars(select(Schedule))).all()
        if s.website_id in (big_a.id, big_b.id)
    ]
    assert len(big) == 10 and all(s.next_due_at > NOW for s in big)


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

    archived = await make_site(db_session, make_user, "tick-archived-due.test")
    archived.archived_at = NOW
    db_session.add(
        Schedule(website_id=archived.id, kind="collect_cwv", frequency="daily", enabled=True,
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


async def test_stuck_running_runs_with_a_long_expired_lease_are_swept(
    db_session: AsyncSession, make_user
) -> None:
    site = await make_site(db_session, make_user, "tick-stuck.test")
    schedule = Schedule(
        website_id=site.id, kind="collect_probes", frequency="three_daily",
        enabled=True, next_due_at=NOW,
    )
    db_session.add(schedule)
    db_session.add(
        JobRun(
            idempotency_key="stuck", kind="collect_probes", website_id=site.id,
            workspace_id=site.workspace_id, window_label="w", params={}, status="running",
            attempt=1, max_attempts=5, observations=0, enqueued_at=NOW - timedelta(hours=3),
            started_at=NOW - timedelta(hours=3),
            lease_expires_at=NOW - STUCK_RUNNING_SWEEP_AFTER - timedelta(minutes=1),
        )
    )
    await db_session.flush()
    assert await expire_stuck_running(db_session, now=NOW) == 1
    run = await db_session.scalar(select(JobRun).where(JobRun.idempotency_key == "stuck"))
    await db_session.refresh(run)
    assert (run.status, run.error_code, run.recoverable, run.lease_expires_at) == (
        "failed", "lease_expired", True, None,
    )
    await db_session.refresh(schedule)
    assert schedule.last_status == "failed" and schedule.failing_since == NOW
    # Balayée : la santé ne la compte plus en `stuck_running`.
    health = await compute_jobs_health(db_session, now=NOW)
    assert health.stuck_running == 0


async def test_a_recently_expired_running_lease_is_not_swept_yet(
    db_session: AsyncSession, make_user
) -> None:
    site = await make_site(db_session, make_user, "tick-stuck-recent.test")
    db_session.add(
        JobRun(
            idempotency_key="recent", kind="collect_probes", website_id=site.id,
            workspace_id=site.workspace_id, window_label="w", params={}, status="running",
            attempt=1, max_attempts=5, observations=0, enqueued_at=NOW - STUCK_RUNNING_GRACE,
            started_at=NOW - STUCK_RUNNING_GRACE,
            lease_expires_at=NOW - STUCK_RUNNING_GRACE,
        )
    )
    await db_session.flush()
    # Bail expiré, mais depuis moins que la marge de balayage : une redélivrance normale
    # de la file peut encore reprendre la tâche.
    assert await expire_stuck_running(db_session, now=NOW) == 0
    run = await db_session.scalar(select(JobRun).where(JobRun.idempotency_key == "recent"))
    assert run.status == "running"


async def test_a_tick_sweeps_a_stuck_running_task_and_updates_the_schedule(
    db_session: AsyncSession, make_user
) -> None:
    site = await make_site(db_session, make_user, "tick-stuck-full.test")
    schedule = Schedule(
        website_id=site.id, kind="collect_probes", frequency="three_daily",
        enabled=True, next_due_at=NOW + timedelta(days=1),
    )
    db_session.add(schedule)
    db_session.add(
        JobRun(
            idempotency_key="stuck-full", kind="collect_probes", website_id=site.id,
            workspace_id=site.workspace_id, window_label="w", params={}, status="running",
            attempt=1, max_attempts=5, observations=0, enqueued_at=NOW - timedelta(hours=3),
            started_at=NOW - timedelta(hours=3), lease_expires_at=NOW - timedelta(hours=2),
        )
    )
    await db_session.flush()
    await _tick(db_session, RecordingQueue())
    run = await db_session.scalar(select(JobRun).where(JobRun.idempotency_key == "stuck-full"))
    await db_session.refresh(run)
    assert (run.status, run.error_code, run.recoverable) == ("failed", "lease_expired", True)
    await db_session.refresh(schedule)
    assert schedule.last_status == "failed" and schedule.failing_since == NOW
    health = await compute_jobs_health(db_session, now=NOW)
    assert health.stuck_running == 0


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
    db_session: AsyncSession, make_user, caplog
) -> None:
    site = await make_site(db_session, make_user, "tick-boom.test")

    class Exploding(RecordingQueue):
        async def enqueue(self, message: TaskMessage) -> None:
            if message.spec.kind == "collect_cwv":
                raise RuntimeError("secret-token-in-url")
            await super().enqueue(message)

    queue = Exploding()
    with caplog.at_level(logging.WARNING, logger="app.services.jobs.scheduler"):
        result = await _tick(db_session, queue)
    assert "secret-token-in-url" not in caplog.text
    errors = [r for r in caplog.records if getattr(r, "event", "") == "job_enqueue_error"]
    assert [(r.levelno, r.error_type) for r in errors] == [(logging.ERROR, "RuntimeError")]
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
    assert queue.failed == ["RuntimeError"] * 6  # visible pour un test : rien n'est avalé


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


async def test_a_redeposited_task_restarts_its_queue_clock(
    db_session: AsyncSession, make_user
) -> None:
    site = await make_site(db_session, make_user, "tick-redeposit.test")
    await _tick(db_session, RecordingQueue(failing_kinds=frozenset({"collect_cwv"})))
    later = NOW + timedelta(hours=3)
    queue = RecordingQueue()
    result = await _tick(db_session, queue, now=later)
    run = await db_session.scalar(
        select(JobRun).where(JobRun.idempotency_key == f"collect_cwv:{site.id}:20260926T0000")
    )
    await db_session.refresh(run)
    assert run.status == "queued" and run.enqueued_at == later
    assert "collect_cwv" in [m.spec.kind for m in queue.messages]
    assert (await compute_jobs_health(db_session, now=later)).stuck_queued == 0
    # Au passage suivant, la tâche fraîchement redéposée n'est pas expirée.
    third = await _tick(db_session, RecordingQueue(), now=later + timedelta(minutes=15))
    await db_session.refresh(run)
    assert third.expired_queued == 0 and run.status == "queued"
    assert result.failed_enqueue == 0


async def test_a_failed_restore_does_not_overwrite_a_schedule_changed_meanwhile(
    db_session: AsyncSession, make_user
) -> None:
    site = await make_site(db_session, make_user, "tick-restore.test")
    edited = NOW + timedelta(days=5)

    class EditingQueue(RecordingQueue):
        async def enqueue(self, message: TaskMessage) -> None:
            if message.spec.kind == "collect_cwv":
                # Le propriétaire modifie le planning pendant le dépôt.
                await db_session.execute(
                    update(Schedule)
                    .where(Schedule.website_id == site.id, Schedule.kind == "collect_cwv")
                    .values(next_due_at=edited)
                )
                raise EnqueueError("network")
            await super().enqueue(message)

    result = await _tick(db_session, EditingQueue())
    assert result.failed_enqueue == 1
    schedules = await _schedules(db_session, site.id)
    await db_session.refresh(schedules["collect_cwv"])
    assert schedules["collect_cwv"].next_due_at == edited


async def test_a_tick_that_cannot_take_the_tick_lock_deposits_nothing(engine) -> None:
    maker = async_sessionmaker(bind=engine, expire_on_commit=False)
    async with maker() as setup:
        user = User(email="tick-glock@example.com", google_sub="tick-glock-sub")
        setup.add(user)
        await setup.flush()
        workspace = Workspace(name="tick-glock", owner_user_id=user.id)
        setup.add(workspace)
        await setup.flush()
        setup.add(WorkspaceMember(workspace_id=workspace.id, user_id=user.id, role="owner"))
        setup.add(Website(workspace_id=workspace.id, domain="tick-glock.test", display_name="g"))
        await setup.commit()
        workspace_id, user_id = workspace.id, user.id

    try:
        async with maker() as holder, maker() as other:
            await lock_key(holder, TICK_LOCK_KEY)  # un autre passage tient le verrou
            queue = RecordingQueue()
            result = await tick(other, queue, now=NOW, batch=100, daily_cap=300, max_attempts=5)
            assert queue.messages == [] and result.enqueued == 0
            assert await other.scalar(select(func.count()).select_from(JobRun)) == 0
            await holder.rollback()
            result = await tick(other, queue, now=NOW, batch=100, daily_cap=300, max_attempts=5)
            assert result.enqueued == 6
    finally:
        async with maker() as cleanup:
            await cleanup.execute(delete(JobRun).where(JobRun.workspace_id == workspace_id))
            await cleanup.execute(delete(JobRun).where(JobRun.kind == "partition_maintenance"))
            await cleanup.execute(delete(Workspace).where(Workspace.id == workspace_id))
            await cleanup.execute(delete(User).where(User.id == user_id))
            await cleanup.commit()


async def test_a_failing_health_computation_never_breaks_the_tick(
    db_session: AsyncSession, make_user, monkeypatch, caplog
) -> None:
    await make_site(db_session, make_user, "tick-health-fail.test")

    async def boom(session, *, now):
        raise RuntimeError("db down secret")

    monkeypatch.setattr("app.services.jobs.scheduler.compute_jobs_health", boom)
    queue = RecordingQueue()
    with caplog.at_level(logging.ERROR, logger="app.services.jobs.scheduler"):
        result = await _tick(db_session, queue)
    assert result.enqueued == 6 and len(queue.messages) == 6
    assert "secret" not in caplog.text
    assert "jobs_health_failed" in [getattr(r, "event", "") for r in caplog.records]


async def test_the_clock_is_normalised_to_utc(db_session: AsyncSession, make_user) -> None:
    site = await make_site(db_session, make_user, "tick-tz.test")
    paris = timezone(timedelta(hours=2))
    # 01:30 à Paris le 27 = 23:30 UTC le 26 : le jour de la limite et de la maintenance
    # est celui de l'UTC.
    local_now = datetime(2026, 9, 27, 1, 30, tzinfo=paris)
    queue = RecordingQueue()
    await tick(db_session, queue, now=local_now, batch=100, daily_cap=300, max_attempts=5)
    keys = {m.spec.key for m in queue.messages}
    assert "partition_maintenance:global:20260926" in keys
    assert await runs_today(db_session, site.workspace_id, now=local_now) == 5
