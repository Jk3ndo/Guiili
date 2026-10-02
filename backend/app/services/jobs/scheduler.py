"""Planificateur : appelé par Cloud Scheduler (`POST /internal/tick`, toutes les 15 min).

Un passage :
1. matérialise les plannings par défaut des sites actifs, expire les tâches restées en
   file plus de 2 h ainsi que les tâches `running` au bail expiré depuis longtemps que
   personne n'a reprises ; commit ;
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
from datetime import UTC, datetime, time, timedelta
from uuid import UUID, uuid4

from sqlalchemy import func, literal, select, text, true, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.job_run import JobRun
from app.models.schedule import Schedule
from app.models.website import Website
from app.services.jobs.health import STUCK_RUNNING_GRACE, compute_jobs_health, report_jobs_health
from app.services.jobs.kinds import (
    BACKFILL_SOURCES,
    KINDS,
    SCHEDULABLE_KINDS,
    RunSpec,
    effective_interval,
    schedule_offset,
    slot_label,
    slot_start,
)
from app.services.jobs.queue import EnqueueError, TaskMessage, TaskQueue
from app.services.jobs.runner import record_schedule_outcome

logger = logging.getLogger(__name__)

STALE_QUEUED_AFTER = timedelta(hours=2)
# Marge après laquelle une ligne `running` au bail expiré, que personne n'a reprise
# (tentatives Cloud Tasks épuisées), est considérée abandonnée. Au-delà de la marge de
# `stuck_running` (le temps d'une redélivrance normale) plus 1 h de sécurité.
STUCK_RUNNING_SWEEP_AFTER = STUCK_RUNNING_GRACE + timedelta(hours=1)
# Verrou consultatif du passage : il sérialise la lecture de la limite quotidienne et
# l'insertion des lignes « en file » (deux passages concurrents la dépasseraient).
TICK_LOCK_KEY = "jobs:tick"


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


async def expire_stuck_running(
    session: AsyncSession, *, now: datetime, older_than: timedelta = STUCK_RUNNING_SWEEP_AFTER
) -> int:
    """Une ligne `running` dont le bail a expiré depuis longtemps ET qu'aucune nouvelle
    livraison n'a reprise (tentatives Cloud Tasks épuisées : l'instance qui l'exécutait
    est morte) resterait `running` pour toujours sinon : `stuck_running >= 1` à chaque
    passage, en continu. Chargée ligne par ligne (verrou de ligne) pour que
    `record_schedule_outcome` puisse faire refléter l'échec au planning."""
    runs = (
        await session.execute(
            select(JobRun)
            .where(
                JobRun.status == "running",
                JobRun.lease_expires_at.is_not(None),
                JobRun.lease_expires_at < now - older_than,
            )
            .with_for_update()
        )
    ).scalars().all()
    for run in runs:
        run.status = "failed"
        run.error_code = "lease_expired"
        run.recoverable = True
        run.finished_at = now
        run.lease_expires_at = None
        if run.started_at is not None:
            run.duration_ms = max(0, int((now - run.started_at).total_seconds() * 1000))
        await record_schedule_outcome(session, run, now=now)
    return len(runs)


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
        .order_by(Schedule.next_due_at, Schedule.id)
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
        .values(
            status="queued", error_code=None, recoverable=None, finished_at=None,
            # Repart de zéro : sinon la tâche redéposée après une longue panne compterait
            # « bloquée en file » (santé) puis serait expirée alors qu'elle vient d'être déposée.
            enqueued_at=now,
        )
    )
    return (reset.rowcount or 0) > 0


async def runs_today(session: AsyncSession, workspace_id: UUID, *, now: datetime) -> int:
    now = now.astimezone(UTC)
    midnight = datetime.combine(now.date(), time.min, tzinfo=UTC)
    count = await session.scalar(
        select(func.count())
        .select_from(JobRun)
        .where(JobRun.workspace_id == workspace_id, JobRun.enqueued_at >= midnight)
    )
    return count or 0


@dataclass(frozen=True, slots=True)
class _Planned:
    """Tâche réservée en phase 2 ; `schedule_id`, `previous_due` et `posed_due` servent à
    restaurer l'échéance si le dépôt échoue (maintenance : `schedule_id` vide)."""

    spec: RunSpec
    schedule_id: UUID | None = None
    previous_due: datetime | None = None
    posed_due: datetime | None = None


def _next_midnight(now: datetime) -> datetime:
    return datetime.combine(now.date() + timedelta(days=1), time.min, tzinfo=UTC)


async def tick(
    session: AsyncSession,
    queue: TaskQueue,
    *,
    now: datetime,
    batch: int,
    daily_cap: int,
    max_attempts: int,
) -> TickResult:
    now = now.astimezone(UTC)
    materialized = await materialize_default_schedules(session, now=now)
    expired = await expire_stale_queued(session, now=now)
    await expire_stuck_running(session, now=now)
    await session.commit()

    planned: list[_Planned] = []
    counts: dict[UUID, int] = {}
    held: dict[UUID, int] = {}
    capped = 0
    got_lock = await session.scalar(
        text("SELECT pg_try_advisory_xact_lock(hashtext(:key))"), {"key": TICK_LOCK_KEY}
    )
    if got_lock:
        for schedule, website in await due_schedules(session, now=now, limit=batch):
            workspace_id = website.workspace_id
            if workspace_id not in counts:
                counts[workspace_id] = await runs_today(session, workspace_id, now=now)
            interval = effective_interval(KINDS[schedule.kind], schedule.frequency)
            previous_due = schedule.next_due_at
            next_slot = slot_start(
                now, interval, offset=schedule_offset(schedule.id, interval)
            ) + interval
            if counts[workspace_id] >= daily_cap:
                # Retenu par la limite du jour : l'échéance avance quand même (au plus tard
                # à minuit UTC NON décalé : `runs_today` se remet à zéro à minuit UTC pile ;
                # reprendre à minuit plutôt qu'au décalage propre est acceptable, vu le
                # plafond de 300 tâches/jour/workspace), sinon les plus anciens
                # plannings seraient re-sélectionnés en tête à chaque passage, priveraient
                # les autres workspaces du lot et compteraient « en retard » (alertes).
                schedule.next_due_at = min(next_slot, _next_midnight(now))
                held[workspace_id] = held.get(workspace_id, 0) + 1
                capped += 1
                continue
            spec = plan_run(schedule, website, now=now)
            schedule.next_due_at = next_slot
            if await insert_queued(session, spec, now=now, max_attempts=max_attempts):
                counts[workspace_id] += 1
                planned.append(_Planned(spec, schedule.id, previous_due, next_slot))
        maintenance = RunSpec("partition_maintenance", None, None, now.strftime("%Y%m%d"))
        if await insert_queued(session, maintenance, now=now, max_attempts=max_attempts):
            planned.append(_Planned(maintenance))
    await session.commit()
    for workspace_id, count in held.items():
        logger.warning(
            "limite quotidienne de tâches atteinte",
            extra={"event": "job_daily_cap_reached", "workspace_id": str(workspace_id), "held": count},
        )

    enqueued = 0
    failed: list[_Planned] = []
    for item in planned:
        spec = item.spec
        try:
            await queue.enqueue(TaskMessage(spec, spec.queue))
        except EnqueueError as exc:
            logger.warning(
                "dépôt de tâche en échec",
                extra={"event": "job_enqueue_failed", "job_key": spec.key, "reason": exc.reason},
            )
            failed.append(item)
        except Exception as exc:  # une file défaillante ne doit pas perdre les tâches suivantes
            # Type seul : le message d'une exception peut embarquer une URL ou un jeton.
            logger.error(
                "dépôt de tâche en erreur inattendue",
                extra={
                    "event": "job_enqueue_error",
                    "job_key": spec.key,
                    "error_type": type(exc).__name__,
                },
            )
            failed.append(item)
        else:
            enqueued += 1

    for item in failed:
        if item.schedule_id is not None and item.previous_due is not None:
            # Conditionnel : si le planning a été modifié entre-temps (PUT du propriétaire),
            # on n'écrase pas son échéance. `synchronize_session` met à jour l'objet chargé.
            await session.execute(
                update(Schedule)
                .where(Schedule.id == item.schedule_id, Schedule.next_due_at == item.posed_due)
                .values(next_due_at=item.previous_due)
                .execution_options(synchronize_session="fetch")
            )
        await session.execute(
            update(JobRun)
            .where(JobRun.idempotency_key == item.spec.key, JobRun.status == "queued")
            .values(status="failed", error_code="enqueue_failed", recoverable=True, finished_at=now)
        )
    if failed:
        await session.commit()

    try:
        report_jobs_health(await compute_jobs_health(session, now=now))
        await session.commit()
    except Exception as exc:  # la santé ne casse jamais un passage dont les dépôts sont faits
        await session.rollback()
        logger.error(
            "santé des tâches indisponible",
            extra={"event": "jobs_health_failed", "error_type": type(exc).__name__},
        )
    return TickResult(
        materialized=materialized,
        enqueued=enqueued,
        capped=capped,
        failed_enqueue=len(failed),
        expired_queued=expired,
    )
