"""Santé des tâches planifiées et alertes d'exploitation.

Objectif (spec §6 mesure 6) : une collecte en échec depuis plus de 24 h doit être vue
par l'équipe AVANT le client. Pas d'e-mail (aucun fournisseur) : une ligne de log
structurée (alerte Cloud Monitoring côté propriétaire), un événement Sentry et un
résumé interne (`GET /internal/jobs/health`)."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

import sentry_sdk
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.job_run import JobRun
from app.models.schedule import Schedule
from app.models.website import Website

logger = logging.getLogger(__name__)

FAILING_AFTER = timedelta(hours=24)
OVERDUE_AFTER = timedelta(hours=2)
STUCK_QUEUED_AFTER = timedelta(hours=1)
# Marge après l'expiration d'un bail : le temps que la file redélivre la tâche.
STUCK_RUNNING_GRACE = timedelta(minutes=5)
# Échecs que seul le client peut lever (reconnexion Google, droits, site injoignable ou
# hors ligne). Tout le reste (dont `api_key_rejected`, `db_transient`,
# `token_refresh_failed`, `bad_request`, `truncated`, l'exécuteur) ainsi que tout code
# inconnu ou absent relève de nous : alerte ERROR (fail-loud).
# Les sources non reliées (`*_not_connected`) sont `skipped` : jamais dans `failing_since`.
CLIENT_ACTION_CODES: frozenset[str] = frozenset(
    {
        "token_unavailable",
        "permission_or_api_disabled",
        "not_found",
        "site_unreachable",
        "unreachable",
    }
)
_SENTRY_MESSAGE = "Tâches planifiées en échec ou en retard"

Capture = Callable[[str, dict[str, Any]], None]


@dataclass(frozen=True, slots=True)
class FailingSchedule:
    website_id: UUID | None
    kind: str
    failing_since: datetime
    error_code: str | None
    client_action: bool


@dataclass(frozen=True, slots=True)
class JobsHealth:
    checked_at: datetime
    failing: tuple[FailingSchedule, ...]
    overdue: int
    stuck_running: int
    stuck_queued: int

    @property
    def internal_failures(self) -> tuple[FailingSchedule, ...]:
        return tuple(item for item in self.failing if not item.client_action)

    @property
    def ok(self) -> bool:
        return not self.failing and not self.overdue and not self.stuck_running and not self.stuck_queued


def _active_schedules():
    return (
        select(Schedule)
        .join(Website, Website.id == Schedule.website_id)
        .where(Schedule.enabled.is_(True), Website.archived_at.is_(None))
    )


async def compute_jobs_health(session: AsyncSession, *, now: datetime) -> JobsHealth:
    failing_rows = (
        await session.execute(
            _active_schedules()
            .where(
                Schedule.failing_since.is_not(None),
                Schedule.failing_since <= now - FAILING_AFTER,
            )
            .order_by(Schedule.failing_since)
        )
    ).scalars().all()
    failing = tuple(
        FailingSchedule(
            website_id=row.website_id,
            kind=row.kind,
            failing_since=row.failing_since,  # type: ignore[arg-type]
            error_code=row.last_error_code,
            client_action=row.last_error_code in CLIENT_ACTION_CODES,
        )
        for row in failing_rows
    )
    overdue = await session.scalar(
        select(func.count()).select_from(
            _active_schedules().where(Schedule.next_due_at < now - OVERDUE_AFTER).subquery()
        )
    )
    # Les comptages `stuck_*` portent sur TOUS les job_runs, sites archivés compris
    # (contrairement à `failing` et `overdue`) : une tâche bloquée reste un défaut de
    # l'exécuteur, quel que soit l'état du site. Un `running` sans bail est bloqué aussi.
    stuck_running = await session.scalar(
        select(func.count())
        .select_from(JobRun)
        .where(
            JobRun.status == "running",
            or_(
                JobRun.lease_expires_at.is_(None),
                JobRun.lease_expires_at < now - STUCK_RUNNING_GRACE,
            ),
        )
    )
    stuck_queued = await session.scalar(
        select(func.count())
        .select_from(JobRun)
        .where(JobRun.status == "queued", JobRun.enqueued_at < now - STUCK_QUEUED_AFTER)
    )
    return JobsHealth(
        checked_at=now,
        failing=failing,
        overdue=overdue or 0,
        stuck_running=stuck_running or 0,
        stuck_queued=stuck_queued or 0,
    )


def _sentry_capture(message: str, extra: dict[str, Any]) -> None:
    with sentry_sdk.new_scope() as scope:
        for key, value in extra.items():
            scope.set_extra(key, value)
        sentry_sdk.capture_message(message, level="error")


def report_jobs_health(health: JobsHealth, *, capture: Capture | None = None) -> None:
    if health.ok:
        logger.info("jobs_health_ok", extra={"event": "jobs_health"})
        return
    internal = len(health.internal_failures)
    extra: dict[str, Any] = {
        "failing_internal": internal,
        "failing_client_action": len(health.failing) - internal,
        "overdue": health.overdue,
        "stuck_running": health.stuck_running,
        "stuck_queued": health.stuck_queued,
        "kinds": sorted({item.kind for item in health.failing}),
    }
    ours = internal or health.overdue or health.stuck_running or health.stuck_queued
    level = logging.ERROR if ours else logging.WARNING
    logger.log(level, "jobs_health_alert", extra={"event": "jobs_health_alert", **extra})
    if level == logging.ERROR:
        try:
            (capture or _sentry_capture)(_SENTRY_MESSAGE, extra)
        except Exception as exc:  # l'alerte de log est déjà émise : ne jamais casser le passage
            # Type seul : le message d'une exception d'envoi peut embarquer un DSN ou une URL.
            logger.warning(
                "jobs_health_capture_failed",
                extra={"event": "jobs_health_capture_failed", "error_type": type(exc).__name__},
            )
