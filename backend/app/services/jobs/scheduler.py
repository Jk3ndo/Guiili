"""Planificateur : appelé par Cloud Scheduler (`POST /internal/tick`, toutes les 15 min).

Un passage :
1. matérialise les plannings par défaut des sites actifs, expire les tâches restées en
   file plus de 2 h ; commit ;
2. réserve les plannings dus (`FOR UPDATE SKIP LOCKED` : deux passages concurrents ne
   prennent jamais le même), applique la limite quotidienne du workspace, avance
   `next_due_at` au créneau suivant et crée les lignes `job_runs` « en file » ; commit ;
3. dépose les tâches dans la file SANS transaction ouverte ;
4. une tâche non déposée redevient due (`next_due_at` restauré, ligne
   `enqueue_failed`) ; commit ;
5. publie la santé des tâches (logs, Sentry)."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from uuid import UUID, uuid4

from sqlalchemy import func, literal, select, true, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.job_run import JobRun
from app.models.schedule import Schedule
from app.models.website import Website
from app.services.jobs.health import compute_jobs_health, report_jobs_health
from app.services.jobs.kinds import (
    BACKFILL_SOURCES,
    KINDS,
    SCHEDULABLE_KINDS,
    RunSpec,
    effective_interval,
    slot_label,
    slot_start,
)
from app.services.jobs.queue import EnqueueError, TaskMessage, TaskQueue

logger = logging.getLogger(__name__)

STALE_QUEUED_AFTER = timedelta(hours=2)


@dataclass(frozen=True, slots=True)
class TickResult:
    materialized: int
    enqueued: int
    capped: int
    failed_enqueue: int
    expired_queued: int


async def materialize_default_schedules(session: AsyncSession, *, now: datetime) -> int:
    created = 0
    for kind in SCHEDULABLE_KINDS:
        source = select(
            func.gen_random_uuid(),
            Website.id,
            literal(kind.name),
            literal(kind.default_frequency),
            true(),
            literal(now),
        ).where(Website.archived_at.is_(None))
        statement = (
            pg_insert(Schedule)
            .from_select(
                ["id", "website_id", "kind", "frequency", "enabled", "next_due_at"], source
            )
            .on_conflict_do_nothing(index_elements=["website_id", "kind"])
        )
        result = await session.execute(statement)
        created += result.rowcount or 0
    return created


async def expire_stale_queued(
    session: AsyncSession, *, now: datetime, older_than: timedelta = STALE_QUEUED_AFTER
) -> int:
    result = await session.execute(
        update(JobRun)
        .where(JobRun.status == "queued", JobRun.enqueued_at < now - older_than)
        .values(status="failed", error_code="not_dispatched", recoverable=True, finished_at=now)
    )
    return result.rowcount or 0


async def due_schedules(
    session: AsyncSession, *, now: datetime, limit: int
) -> list[tuple[Schedule, Website]]:
    rows = await session.execute(
        select(Schedule, Website)
        .join(Website, Website.id == Schedule.website_id)
        .where(
            Schedule.enabled.is_(True),
            Schedule.next_due_at <= now,
            Website.archived_at.is_(None),
        )
        .order_by(Schedule.next_due_at)
        .limit(limit)
        .with_for_update(of=Schedule, skip_locked=True)
    )
    return [(schedule, website) for schedule, website in rows.all()]


def plan_run(schedule: Schedule, website: Website, *, now: datetime) -> RunSpec:
    kind = KINDS[schedule.kind]
    label = slot_label(slot_start(now, effective_interval(kind, schedule.frequency)))
    if kind.source in BACKFILL_SOURCES and schedule.backfill_done_at is None:
        return RunSpec(
            "backfill", website.id, website.workspace_id, f"{kind.source}-{label}",
            {"source": kind.source},
        )
    return RunSpec(kind.name, website.id, website.workspace_id, label)


async def insert_queued(
    session: AsyncSession, spec: RunSpec, *, now: datetime, max_attempts: int
) -> bool:
    """Crée la ligne « en file » ; vrai si elle est nouvelle, ou si un dépôt précédent
    de la même tâche avait échoué (elle repart en file)."""
    result = await session.execute(
        pg_insert(JobRun)
        .values(
            id=uuid4(),
            idempotency_key=spec.key,
            kind=spec.kind,
            website_id=spec.website_id,
            workspace_id=spec.workspace_id,
            window_label=spec.window,
            params=dict(spec.params),
            status="queued",
            attempt=0,
            max_attempts=max_attempts,
            enqueued_at=now,
            observations=0,
        )
        .on_conflict_do_nothing(index_elements=["idempotency_key"])
        .returning(JobRun.id)
    )
    if result.scalar_one_or_none() is not None:
        return True
    reset = await session.execute(
        update(JobRun)
        .where(
            JobRun.idempotency_key == spec.key,
            JobRun.status == "failed",
            JobRun.error_code == "enqueue_failed",
        )
        .values(status="queued", error_code=None, recoverable=None, finished_at=None)
    )
    return (reset.rowcount or 0) > 0


async def runs_today(session: AsyncSession, workspace_id: UUID, *, now: datetime) -> int:
    midnight = datetime.combine(now.date(), time.min, tzinfo=now.tzinfo)
    count = await session.scalar(
        select(func.count())
        .select_from(JobRun)
        .where(JobRun.workspace_id == workspace_id, JobRun.enqueued_at >= midnight)
    )
    return count or 0


async def tick(
    session: AsyncSession,
    queue: TaskQueue,
    *,
    now: datetime,
    batch: int,
    daily_cap: int,
    max_attempts: int,
) -> TickResult:
    materialized = await materialize_default_schedules(session, now=now)
    expired = await expire_stale_queued(session, now=now)
    await session.commit()

    # (planning ou None pour la maintenance, échéance précédente, tâche)
    planned: list[tuple[Schedule | None, datetime | None, RunSpec]] = []
    counts: dict[UUID, int] = {}
    capped = 0
    for schedule, website in await due_schedules(session, now=now, limit=batch):
        workspace_id = website.workspace_id
        if workspace_id not in counts:
            counts[workspace_id] = await runs_today(session, workspace_id, now=now)
        if counts[workspace_id] >= daily_cap:
            capped += 1
            continue
        counts[workspace_id] += 1
        spec = plan_run(schedule, website, now=now)
        previous_due = schedule.next_due_at
        interval = effective_interval(KINDS[schedule.kind], schedule.frequency)
        schedule.next_due_at = slot_start(now, interval) + interval
        if await insert_queued(session, spec, now=now, max_attempts=max_attempts):
            planned.append((schedule, previous_due, spec))
    maintenance = RunSpec("partition_maintenance", None, None, now.strftime("%Y%m%d"))
    if await insert_queued(session, maintenance, now=now, max_attempts=max_attempts):
        planned.append((None, None, maintenance))
    await session.commit()

    enqueued = 0
    failed: list[tuple[Schedule | None, datetime | None, RunSpec]] = []
    for item in planned:
        spec = item[2]
        try:
            await queue.enqueue(TaskMessage(spec, spec.queue))
        except Exception as exc:  # une file défaillante ne doit pas perdre les tâches suivantes
            # `EnqueueError.reason` est un code stable ; pour toute autre exception, le type
            # seul (le message peut embarquer une URL ou un jeton).
            reason = exc.reason if isinstance(exc, EnqueueError) else type(exc).__name__
            logger.warning(
                "dépôt de tâche en échec",
                extra={"event": "job_enqueue_failed", "job_key": spec.key, "reason": reason},
            )
            failed.append(item)
        else:
            enqueued += 1

    for schedule, previous_due, spec in failed:
        if schedule is not None and previous_due is not None:
            # Par l'ORM (objet encore chargé, `expire_on_commit=False`) : une mise à jour
            # SQL directe laisserait l'objet en mémoire périmé.
            schedule.next_due_at = previous_due
        await session.execute(
            update(JobRun)
            .where(JobRun.idempotency_key == spec.key, JobRun.status == "queued")
            .values(status="failed", error_code="enqueue_failed", recoverable=True, finished_at=now)
        )
    if failed:
        await session.commit()

    report_jobs_health(await compute_jobs_health(session, now=now))
    await session.commit()
    return TickResult(
        materialized=materialized,
        enqueued=enqueued,
        capped=capped,
        failed_enqueue=len(failed),
        expired_queued=expired,
    )
