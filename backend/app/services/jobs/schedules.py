"""Plannings d'un site pour l'interface « Suivi automatique »."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.schedule import Schedule
from app.services.jobs.kinds import SCHEDULABLE_KINDS, TaskKind, effective_interval
from app.services.jobs.messages import error_message


@dataclass(frozen=True, slots=True)
class ScheduleView:
    kind: str
    label: str
    frequency: str
    enabled: bool
    allowed_frequencies: tuple[str, ...]
    floor_hours: int
    next_due_at: datetime | None
    last_run_at: datetime | None
    last_status: str | None
    last_success_at: datetime | None
    failing_since: datetime | None
    last_error_code: str | None
    last_error: str | None
    backfill_done_at: datetime | None


async def schedule_views(session: AsyncSession, website_id: UUID) -> list[ScheduleView]:
    rows = {
        row.kind: row
        for row in (
            await session.execute(select(Schedule).where(Schedule.website_id == website_id))
        ).scalars()
    }
    views: list[ScheduleView] = []
    for kind in SCHEDULABLE_KINDS:
        row = rows.get(kind.name)
        views.append(
            ScheduleView(
                kind=kind.name,
                label=kind.label,
                frequency=row.frequency if row else str(kind.default_frequency),
                enabled=row.enabled if row else True,
                allowed_frequencies=kind.allowed_frequencies(),
                floor_hours=int(kind.floor.total_seconds() // 3600),
                next_due_at=row.next_due_at if row else None,
                last_run_at=row.last_run_at if row else None,
                last_status=row.last_status if row else None,
                last_success_at=row.last_success_at if row else None,
                failing_since=row.failing_since if row else None,
                last_error_code=row.last_error_code if row else None,
                last_error=error_message(row.last_error_code) if row else None,
                backfill_done_at=row.backfill_done_at if row else None,
            )
        )
    return views


async def upsert_schedule(
    session: AsyncSession,
    *,
    website_id: UUID,
    kind: TaskKind,
    frequency: str,
    enabled: bool,
    now: datetime,
) -> Schedule:
    await session.execute(
        pg_insert(Schedule)
        .values(
            id=uuid4(),
            website_id=website_id,
            kind=kind.name,
            frequency=frequency,
            enabled=enabled,
            next_due_at=now,
        )
        .on_conflict_do_update(
            index_elements=["website_id", "kind"],
            set_={"frequency": frequency, "enabled": enabled, "updated_at": now},
        )
    )
    schedule = (
        await session.execute(
            select(Schedule)
            .where(Schedule.website_id == website_id, Schedule.kind == kind.name)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one()
    if schedule.last_run_at is not None:
        # Une fréquence plus serrée rapproche l'échéance (jamais dans le passé).
        candidate = max(schedule.last_run_at + effective_interval(kind, frequency), now)
        schedule.next_due_at = min(schedule.next_due_at, candidate)
    return schedule
