import asyncio
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import delete, func, select, text
from sqlalchemy.exc import DBAPIError, ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.job_run import JobRun
from app.models.metric_point import MetricPoint
from app.models.schedule import Schedule
from app.models.user import User
from app.models.website import Website
from app.models.workspace import Workspace
from app.models.workspace_member import WorkspaceMember
from app.services.jobs.kinds import (
    KINDS,
    RunSpec,
    effective_interval,
    slot_label,
    slot_start,
)
from app.services.jobs.runner import HandlerOutcome, claim_run, execute_run, lock_key
from app.services.metrics.types import SourceError
from tests.jobs_fakes import LIMITS, make_site

NOW = datetime(2026, 9, 26, 6, 7, tzinfo=UTC)


def _spec(site: Website, window: str = "w1", kind: str = "collect_probes") -> RunSpec:
    return RunSpec(kind, site.id, site.workspace_id, window)


def _clock():
    return NOW


async def _ok(session, run) -> HandlerOutcome:
    return HandlerOutcome(observations=2)


def test_kinds_floors_frequencies_and_slots() -> None:
    assert KINDS["collect_ga4"].allowed_frequencies() == ("three_daily", "daily", "every_3_days", "weekly")
    assert KINDS["collect_probes"].allowed_frequencies()[0] == "hourly"
    # Plancher appliqué même si la base contenait une fréquence trop élevée.
    assert effective_interval(KINDS["collect_ga4"], "hourly") == timedelta(hours=8)
    assert slot_start(NOW, timedelta(hours=8)) == datetime(2026, 9, 26, 0, 0, tzinfo=UTC)
    assert slot_start(NOW, timedelta(hours=1)) == datetime(2026, 9, 26, 6, 0, tzinfo=UTC)
    assert slot_label(slot_start(NOW, timedelta(days=1))) == "20260926T0000"


def test_run_spec_key_queue_and_payload() -> None:
    spec = RunSpec("backfill", None, None, "ga4-20260926T0000", {"source": "ga4"})
    assert spec.key == "backfill:global:ga4-20260926T0000"
    assert spec.queue == "ga4"
    assert RunSpec("collect_probes", None, None, "w").queue == "light"
    assert spec.to_payload() == {
        "kind": "backfill",
        "website_id": None,
        "workspace_id": None,
        "window": "ga4-20260926T0000",
        "params": {"source": "ga4"},
    }


async def test_first_claim_starts_the_run_with_a_lease(db_session: AsyncSession, make_user) -> None:
    site = await make_site(db_session, make_user, "run-first.test")
    claim = await claim_run(db_session, _spec(site), now=NOW, limits=LIMITS)
    assert claim.status == "claimed"
    assert claim.run.status == "running" and claim.run.attempt == 1
    assert claim.run.lease_expires_at == NOW + LIMITS.lease
    assert claim.run.idempotency_key == f"collect_probes:{site.id}:w1"


async def test_a_second_delivery_during_the_lease_is_busy(
    db_session: AsyncSession, make_user
) -> None:
    site = await make_site(db_session, make_user, "run-busy.test")
    await claim_run(db_session, _spec(site), now=NOW, limits=LIMITS)
    claim = await claim_run(db_session, _spec(site), now=NOW + timedelta(minutes=5), limits=LIMITS)
    assert claim.status == "busy" and claim.run.attempt == 1


async def test_an_expired_lease_is_reclaimed_with_a_new_attempt(
    db_session: AsyncSession, make_user
) -> None:
    site = await make_site(db_session, make_user, "run-lease.test")
    await claim_run(db_session, _spec(site), now=NOW, limits=LIMITS)
    claim = await claim_run(db_session, _spec(site), now=NOW + timedelta(minutes=16), limits=LIMITS)
    assert claim.status == "claimed" and claim.run.attempt == 2


async def test_an_expired_lease_on_the_last_attempt_is_exhausted(
    db_session: AsyncSession, make_user
) -> None:
    site = await make_site(db_session, make_user, "run-exhausted.test")
    limits = replace(LIMITS, max_attempts=1)
    await claim_run(db_session, _spec(site), now=NOW, limits=limits)
    claim = await claim_run(db_session, _spec(site), now=NOW + timedelta(minutes=16), limits=limits)
    assert claim.status == "exhausted"
    assert claim.run.status == "failed" and claim.run.error_code == "lease_expired"


async def test_a_finished_run_is_never_run_again(db_session: AsyncSession, make_user) -> None:
    site = await make_site(db_session, make_user, "run-dup.test")
    calls: list[str] = []

    async def handler(session, run) -> HandlerOutcome:
        calls.append(run.idempotency_key)
        return HandlerOutcome(observations=2)

    first = await execute_run(
        db_session, _spec(site), handlers={"collect_probes": handler}, limits=LIMITS, clock=_clock
    )
    again = await execute_run(
        db_session, _spec(site), handlers={"collect_probes": handler}, limits=LIMITS, clock=_clock
    )
    assert (first.claim, first.status, first.retry) == ("claimed", "succeeded", False)
    assert (again.claim, again.retry) == ("duplicate", False)
    assert len(calls) == 1
    run = await db_session.scalar(select(JobRun).where(JobRun.website_id == site.id))
    assert run.observations == 2 and run.lease_expires_at is None and run.duration_ms == 0


async def test_workspace_concurrency_is_limited(db_session: AsyncSession, make_user) -> None:
    site = await make_site(db_session, make_user, "run-conc.test")
    other = await make_site(db_session, make_user, "run-conc-other.test")
    assert (await claim_run(db_session, _spec(site, "a"), now=NOW, limits=LIMITS)).status == "claimed"
    assert (await claim_run(db_session, _spec(site, "b"), now=NOW, limits=LIMITS)).status == "claimed"
    throttled = await claim_run(db_session, _spec(site, "c"), now=NOW, limits=LIMITS)
    assert throttled.status == "throttled" and throttled.run.status == "queued"
    # Un autre workspace n'est pas freiné.
    assert (await claim_run(db_session, _spec(other, "a"), now=NOW, limits=LIMITS)).status == "claimed"


async def test_a_recoverable_error_fails_and_asks_for_a_retry(
    db_session: AsyncSession, make_user
) -> None:
    site = await make_site(db_session, make_user, "run-retry.test")

    async def quota(session, run) -> HandlerOutcome:
        raise SourceError("quota", recoverable=True)

    result = await execute_run(
        db_session, _spec(site), handlers={"collect_probes": quota}, limits=LIMITS, clock=_clock
    )
    assert (result.status, result.retry) == ("failed", True)
    retried = await execute_run(
        db_session, _spec(site), handlers={"collect_probes": _ok}, limits=LIMITS, clock=_clock
    )
    assert (retried.claim, retried.status) == ("claimed", "succeeded")
    run = await db_session.scalar(select(JobRun).where(JobRun.website_id == site.id))
    assert run.attempt == 2 and run.error_code is None


async def test_a_fatal_error_is_not_retried(db_session: AsyncSession, make_user) -> None:
    site = await make_site(db_session, make_user, "run-fatal.test")

    async def revoked(session, run) -> HandlerOutcome:
        raise SourceError("token_unavailable", recoverable=False)

    result = await execute_run(
        db_session, _spec(site), handlers={"collect_probes": revoked}, limits=LIMITS, clock=_clock
    )
    assert (result.status, result.retry) == ("failed", False)
    again = await execute_run(
        db_session, _spec(site), handlers={"collect_probes": _ok}, limits=LIMITS, clock=_clock
    )
    assert again.claim == "exhausted"


async def test_not_applicable_is_skipped_and_keeps_the_schedule_healthy(
    db_session: AsyncSession, make_user
) -> None:
    site = await make_site(db_session, make_user, "run-skip.test")
    db_session.add(
        Schedule(
            website_id=site.id, kind="collect_ga4", frequency="daily", enabled=True,
            next_due_at=NOW, failing_since=NOW - timedelta(days=2),
        )
    )
    await db_session.flush()

    async def unlinked(session, run) -> HandlerOutcome:
        raise SourceError("ga4_not_connected", recoverable=False, not_applicable=True)

    result = await execute_run(
        db_session, _spec(site, kind="collect_ga4"), handlers={"collect_ga4": unlinked},
        limits=LIMITS, clock=_clock,
    )
    assert (result.status, result.retry) == ("skipped", False)
    schedule = await db_session.scalar(select(Schedule).where(Schedule.website_id == site.id))
    assert schedule.last_status == "skipped"
    assert schedule.last_error_code == "ga4_not_connected"
    assert schedule.failing_since is None


async def test_an_unexpected_exception_rolls_back_partial_writes(
    db_session: AsyncSession, make_user
) -> None:
    site = await make_site(db_session, make_user, "run-crash.test")
    # Le rollback expire les objets de la session : on garde l'identifiant à part.
    site_id = site.id

    async def crash(session, run) -> HandlerOutcome:
        session.add(
            MetricPoint(
                website_id=site_id, source="probe", metric="page_up", dim_key="",
                day=date(2026, 9, 26), value=1.0, dims={}, collected_at=NOW,
            )
        )
        await session.flush()
        raise RuntimeError("bogue")

    result = await execute_run(
        db_session, _spec(site), handlers={"collect_probes": crash}, limits=LIMITS, clock=_clock
    )
    assert (result.status, result.retry) == ("failed", True)
    run = await db_session.scalar(select(JobRun).where(JobRun.website_id == site_id))
    assert run.error_code == "internal_error" and run.error_detail == "RuntimeError"
    assert await db_session.scalar(select(func.count()).select_from(MetricPoint)) == 0


async def test_success_and_failure_update_the_schedule(db_session: AsyncSession, make_user) -> None:
    site = await make_site(db_session, make_user, "run-schedule.test")
    db_session.add(
        Schedule(
            website_id=site.id, kind="collect_probes", frequency="daily", enabled=True,
            next_due_at=NOW,
        )
    )
    await db_session.flush()

    async def broken(session, run) -> HandlerOutcome:
        raise SourceError("unreachable", recoverable=True)

    await execute_run(
        db_session, _spec(site, "f"), handlers={"collect_probes": broken}, limits=LIMITS, clock=_clock
    )
    schedule = await db_session.scalar(select(Schedule).where(Schedule.website_id == site.id))
    assert schedule.last_status == "failed" and schedule.failing_since == NOW
    assert schedule.last_error_code == "unreachable"

    await execute_run(
        db_session, _spec(site, "s"), handlers={"collect_probes": _ok}, limits=LIMITS, clock=_clock
    )
    await db_session.refresh(schedule)
    assert schedule.last_status == "succeeded" and schedule.failing_since is None
    assert schedule.last_success_at == NOW and schedule.last_error_code is None


async def test_a_backfill_success_marks_the_collect_schedule(
    db_session: AsyncSession, make_user
) -> None:
    site = await make_site(db_session, make_user, "run-backfill.test")
    db_session.add(
        Schedule(
            website_id=site.id, kind="collect_gsc", frequency="daily", enabled=True,
            next_due_at=NOW,
        )
    )
    await db_session.flush()
    spec = RunSpec("backfill", site.id, site.workspace_id, "gsc-x", {"source": "gsc"})
    await execute_run(db_session, spec, handlers={"backfill": _ok}, limits=LIMITS, clock=_clock)
    schedule = await db_session.scalar(select(Schedule).where(Schedule.website_id == site.id))
    assert schedule.backfill_done_at == NOW and schedule.last_status == "succeeded"


async def test_a_second_delivery_waits_for_the_key_lock_then_sees_the_run_busy(engine) -> None:
    maker = async_sessionmaker(bind=engine, expire_on_commit=False)
    async with maker() as setup:
        user = User(email="jobs-lock@example.com", google_sub="jobs-lock-sub")
        setup.add(user)
        await setup.flush()
        workspace = Workspace(name="jobs-lock", owner_user_id=user.id)
        setup.add(workspace)
        await setup.flush()
        setup.add(WorkspaceMember(workspace_id=workspace.id, user_id=user.id, role="owner"))
        site = Website(workspace_id=workspace.id, domain="jobs-lock.test", display_name="lock")
        setup.add(site)
        await setup.commit()
        site_id, workspace_id, user_id = site.id, workspace.id, user.id

    spec = RunSpec("collect_probes", site_id, workspace_id, "lock")
    try:
        async with maker() as holder, maker() as other:
            first = await claim_run(holder, spec, now=NOW, limits=LIMITS)  # verrou tenu
            assert first.status == "claimed"
            task = asyncio.create_task(claim_run(other, spec, now=NOW, limits=LIMITS))
            waiting = 0
            for _ in range(200):
                assert not task.done(), "la seconde livraison doit attendre le verrou de la clé"
                waiting = await holder.scalar(
                    text("SELECT count(*) FROM pg_locks WHERE locktype = 'advisory' AND NOT granted")
                )
                if waiting:
                    break
                await asyncio.sleep(0.05)
            assert waiting, "la seconde livraison doit attendre le verrou de la clé"
            await holder.commit()
            second = await asyncio.wait_for(task, timeout=10)
            assert second.status == "busy"
            await other.commit()
    finally:
        async with maker() as cleanup:
            await cleanup.execute(delete(Website).where(Website.id == site_id))
            await cleanup.execute(delete(Workspace).where(Workspace.id == workspace_id))
            await cleanup.execute(delete(User).where(User.id == user_id))
            await cleanup.commit()


async def test_lock_key_is_reentrant_in_a_transaction(db_session: AsyncSession) -> None:
    await lock_key(db_session, "x")
    await lock_key(db_session, "x")  # ne se bloque pas lui-même


class _PgError(Exception):
    def __init__(self, message: str, sqlstate: str | None = None) -> None:
        super().__init__(message)
        self.sqlstate = sqlstate


async def test_a_transient_database_error_is_recoverable_but_a_programming_error_is_not_masked(
    db_session: AsyncSession, make_user
) -> None:
    site = await make_site(db_session, make_user, "run-dberr.test")

    async def lock_timeout(session, run) -> HandlerOutcome:
        raise DBAPIError("INSERT", {}, _PgError("canceling statement", "55P03"))

    async def partition(session, run) -> HandlerOutcome:
        raise DBAPIError("INSERT", {}, _PgError("violates partition constraint of relation"))

    async def bad_sql(session, run) -> HandlerOutcome:
        raise ProgrammingError("SELECT", {}, _PgError("column does not exist", "42703"))

    expectations = [
        ("l", lock_timeout, "db_transient", "DBAPIError"),
        ("p", partition, "db_transient", "DBAPIError"),
        ("b", bad_sql, "internal_error", "ProgrammingError"),
    ]
    for window, handler, code, detail in expectations:
        result = await execute_run(
            db_session, _spec(site, window), handlers={"collect_probes": handler},
            limits=LIMITS, clock=_clock,
        )
        assert (result.status, result.retry) == ("failed", True)
        run = await db_session.scalar(select(JobRun).where(JobRun.idempotency_key == f"collect_probes:{site.id}:{window}"))
        assert (run.error_code, run.error_detail) == (code, detail)


async def test_an_unknown_kind_fails_definitively(db_session: AsyncSession, make_user) -> None:
    site = await make_site(db_session, make_user, "run-unknown.test")
    result = await execute_run(db_session, _spec(site), handlers={}, limits=LIMITS, clock=_clock)
    assert (result.status, result.retry) == ("failed", False)


async def test_the_last_recoverable_attempt_does_not_ask_for_a_retry(
    db_session: AsyncSession, make_user
) -> None:
    site = await make_site(db_session, make_user, "run-lastretry.test")
    limits = replace(LIMITS, max_attempts=1)

    async def quota(session, run) -> HandlerOutcome:
        raise SourceError("quota", recoverable=True)

    result = await execute_run(
        db_session, _spec(site), handlers={"collect_probes": quota}, limits=limits, clock=_clock
    )
    assert (result.status, result.retry) == ("failed", False)


async def test_busy_and_throttled_deliveries_ask_the_queue_to_retry(
    db_session: AsyncSession, make_user
) -> None:
    site = await make_site(db_session, make_user, "run-busyretry.test")
    await claim_run(db_session, _spec(site, "a"), now=NOW, limits=LIMITS)
    busy = await execute_run(
        db_session, _spec(site, "a"), handlers={"collect_probes": _ok}, limits=LIMITS, clock=_clock
    )
    assert (busy.claim, busy.retry) == ("busy", True)
    await claim_run(db_session, _spec(site, "b"), now=NOW, limits=LIMITS)
    throttled = await execute_run(
        db_session, _spec(site, "c"), handlers={"collect_probes": _ok}, limits=LIMITS, clock=_clock
    )
    assert (throttled.claim, throttled.retry) == ("throttled", True)


async def test_a_handler_commit_before_failing_survives_the_rollback(
    db_session: AsyncSession, make_user
) -> None:
    site = await make_site(db_session, make_user, "run-commit.test")

    async def reauth_then_fail(session, run) -> HandlerOutcome:
        session.add(
            MetricPoint(
                website_id=site.id, source="probe", metric="page_up", dim_key="",
                day=date(2026, 9, 26), value=1.0, dims={}, collected_at=NOW,
            )
        )
        await session.commit()  # effet à conserver (ex. connexion passée à needs_reauth)
        raise SourceError("token_unavailable", recoverable=False)

    result = await execute_run(
        db_session, _spec(site), handlers={"collect_probes": reauth_then_fail},
        limits=LIMITS, clock=_clock,
    )
    assert (result.status, result.retry) == ("failed", False)
    assert await db_session.scalar(select(func.count()).select_from(MetricPoint)) == 1
