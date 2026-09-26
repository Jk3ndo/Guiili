"""Exécution d'une tâche : clé d'idempotence, bail, reprises, classification des
erreurs et limites par workspace.

La réclamation prend d'abord un verrou consultatif sur la clé de la tâche, puis sur le
workspace, AVANT toute lecture : deux livraisons de la même tâche ne s'exécutent jamais
ensemble, et le décompte des tâches en cours d'un workspace est exact. La réclamation
est committée avant le travail : aucune transaction ne reste ouverte pendant la
collecte réseau.

Ordre de prise des verrous (constant, pour éviter les interblocages) : clé de la tâche,
puis workspace, puis, dans le gestionnaire, `lock_metrics` (site, source).

Un gestionnaire dont un effet doit survivre à un échec (par exemple une connexion Google
passée à `needs_reauth` par la résolution des identifiants) COMMITTE cet effet lui-même
avant de lever : `execute_run` fait `rollback` sur toute erreur."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal
from uuid import uuid4

from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.models.job_run import JobRun
from app.models.schedule import Schedule
from app.services.jobs.kinds import COLLECT_KIND_BY_SOURCE, RunSpec
from app.services.metrics.types import SourceError, utc_now

logger = logging.getLogger(__name__)

ClaimStatus = Literal["claimed", "duplicate", "busy", "exhausted", "throttled"]

# SQLSTATE d'un verrou refusé (`lock_timeout`), d'un interblocage ou d'un échec de
# sérialisation : transitoires, une nouvelle tentative a du sens.
_TRANSIENT_SQLSTATES = frozenset({"55P03", "40P01", "40001"})


@dataclass(frozen=True, slots=True)
class JobLimits:
    lease: timedelta
    max_attempts: int
    workspace_concurrency: int

    @classmethod
    def from_settings(cls, settings: Settings) -> JobLimits:
        return cls(
            lease=timedelta(seconds=settings.jobs_lease_seconds),
            max_attempts=settings.jobs_max_attempts,
            workspace_concurrency=settings.jobs_workspace_concurrency,
        )


@dataclass(frozen=True, slots=True)
class Claim:
    status: ClaimStatus
    run: JobRun


@dataclass(frozen=True, slots=True)
class HandlerOutcome:
    status: Literal["succeeded", "skipped"] = "succeeded"
    observations: int = 0
    note: str | None = None


Handler = Callable[[AsyncSession, JobRun], Awaitable[HandlerOutcome]]


@dataclass(frozen=True, slots=True)
class RunResult:
    claim: ClaimStatus
    status: str | None
    # La file doit-elle réessayer plus tard (réponse non 2xx) ?
    retry: bool


async def lock_key(session: AsyncSession, key: str) -> None:
    await session.execute(text("SELECT pg_advisory_xact_lock(hashtext(:key))"), {"key": key})


def is_transient_db_error(exc: BaseException) -> bool:
    """Erreur de base de données liée à un verrou ou à la maintenance des partitions
    (récupérable). Une vraie erreur de programmation (SQL invalide, colonne inconnue,
    violation d'unicité…) n'en est pas une : elle reste classée `internal_error`."""
    if not isinstance(exc, DBAPIError):
        return False
    orig = exc.orig
    sqlstate = getattr(orig, "sqlstate", None) or getattr(orig, "pgcode", None)
    if sqlstate in _TRANSIENT_SQLSTATES:
        return True
    # Ligne sans partition (`no partition of relation ... found for row`) ou violation
    # de la contrainte d'une partition en cours de rattachement.
    message = str(orig)
    return "partition constraint" in message or "no partition of relation" in message


def _close(
    run: JobRun,
    *,
    status: str,
    error_code: str | None,
    recoverable: bool | None,
    now: datetime,
    observations: int = 0,
    detail: str | None = None,
) -> None:
    run.status = status
    run.error_code = error_code
    run.error_detail = detail
    run.recoverable = recoverable
    run.observations = observations
    run.finished_at = now
    run.lease_expires_at = None
    if run.started_at is not None:
        run.duration_ms = max(0, int((now - run.started_at).total_seconds() * 1000))


async def claim_run(
    session: AsyncSession, spec: RunSpec, *, now: datetime, limits: JobLimits
) -> Claim:
    await lock_key(session, f"job:{spec.key}")
    await session.execute(
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
            max_attempts=limits.max_attempts,
            enqueued_at=now,
            observations=0,
        )
        .on_conflict_do_nothing(index_elements=["idempotency_key"])
    )
    run = (
        await session.execute(
            select(JobRun)
            .where(JobRun.idempotency_key == spec.key)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one()

    if run.status in ("succeeded", "skipped"):
        return Claim("duplicate", run)
    lease_valid = run.lease_expires_at is not None and run.lease_expires_at > now
    if run.status == "running" and lease_valid:
        return Claim("busy", run)
    if run.status == "failed" and run.recoverable is False:
        return Claim("exhausted", run)
    if run.attempt >= run.max_attempts:
        if run.status == "running":  # bail expiré sur la dernière tentative
            _close(run, status="failed", error_code="lease_expired", recoverable=True, now=now)
            await session.flush()
        return Claim("exhausted", run)
    if run.workspace_id is not None:
        await lock_key(session, f"workspace:{run.workspace_id}")
        running = await session.scalar(
            select(func.count())
            .select_from(JobRun)
            .where(
                JobRun.workspace_id == run.workspace_id,
                JobRun.status == "running",
                JobRun.lease_expires_at > now,
                JobRun.id != run.id,
            )
        )
        if (running or 0) >= limits.workspace_concurrency:
            return Claim("throttled", run)
    run.status = "running"
    run.attempt += 1
    run.started_at = now
    run.finished_at = None
    run.lease_expires_at = now + limits.lease
    await session.flush()
    return Claim("claimed", run)


async def record_schedule_outcome(session: AsyncSession, run: JobRun, *, now: datetime) -> None:
    if run.website_id is None:
        return
    if run.kind == "backfill":
        kind = COLLECT_KIND_BY_SOURCE.get(str(run.params.get("source", "")))
    else:
        kind = run.kind
    if kind is None:
        return
    schedule = (
        await session.execute(
            select(Schedule)
            .where(Schedule.website_id == run.website_id, Schedule.kind == kind)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if schedule is None:
        return
    schedule.last_run_at = now
    schedule.last_status = run.status
    if run.status == "succeeded":
        schedule.last_success_at = now
        schedule.failing_since = None
        schedule.last_error_code = None
        if run.kind == "backfill":
            schedule.backfill_done_at = now
    elif run.status == "failed":
        schedule.last_error_code = run.error_code
        if schedule.failing_since is None:
            schedule.failing_since = now
    else:  # « ignorée » : rien à collecter, ce n'est pas un échec
        schedule.last_error_code = run.error_code
        schedule.failing_since = None


async def _finish(
    session: AsyncSession,
    run_id,
    *,
    status: str,
    error_code: str | None,
    recoverable: bool | None,
    now: datetime,
    observations: int = 0,
    detail: str | None = None,
) -> RunResult:
    run = await session.get(JobRun, run_id, with_for_update=True, populate_existing=True)
    if run is None:  # site supprimé pendant l'exécution (cascade)
        await session.commit()
        return RunResult("claimed", None, retry=False)
    _close(
        run,
        status=status,
        error_code=error_code,
        recoverable=recoverable,
        now=now,
        observations=observations,
        detail=detail,
    )
    await record_schedule_outcome(session, run, now=now)
    await session.commit()
    retry = status == "failed" and recoverable is True and run.attempt < run.max_attempts
    return RunResult("claimed", status, retry=retry)


async def execute_run(
    session: AsyncSession,
    spec: RunSpec,
    *,
    handlers: Mapping[str, Handler],
    limits: JobLimits,
    clock: Callable[[], datetime] = utc_now,
) -> RunResult:
    claim = await claim_run(session, spec, now=clock(), limits=limits)
    await session.commit()
    if claim.status != "claimed":
        return RunResult(claim.status, claim.run.status, retry=claim.status in ("busy", "throttled"))

    run_id = claim.run.id
    handler = handlers.get(spec.kind)
    log_extra = {"job_kind": spec.kind, "job_key": spec.key}
    try:
        if handler is None:
            raise SourceError("unknown_kind", recoverable=False)
        outcome = await handler(session, claim.run)
    except SourceError as exc:
        await session.rollback()
        if exc.not_applicable:
            return await _finish(
                session, run_id, status="skipped", error_code=exc.reason, recoverable=None,
                now=clock(),
            )
        logger.warning(
            "tâche en échec",
            extra={**log_extra, "event": "job_failed", "error_code": exc.reason,
                   "recoverable": exc.recoverable},
        )
        return await _finish(
            session, run_id, status="failed", error_code=exc.reason,
            recoverable=exc.recoverable, now=clock(),
        )
    except Exception as exc:
        await session.rollback()
        if is_transient_db_error(exc):
            logger.warning(
                "tâche en échec transitoire de base de données",
                extra={**log_extra, "event": "job_db_transient"},
            )
            return await _finish(
                session, run_id, status="failed", error_code="db_transient", recoverable=True,
                now=clock(), detail=type(exc).__name__,
            )
        logger.exception("tâche en échec inattendu", extra={**log_extra, "event": "job_crashed"})
        return await _finish(
            session, run_id, status="failed", error_code="internal_error", recoverable=True,
            now=clock(), detail=type(exc).__name__,
        )
    return await _finish(
        session, run_id, status=outcome.status, error_code=outcome.note, recoverable=None,
        now=clock(), observations=outcome.observations,
    )
