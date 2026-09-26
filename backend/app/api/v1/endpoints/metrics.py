from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Annotated, Self
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, model_validator
from sqlalchemy import select

from app.api.deps import CurrentUserDep, SessionDep
from app.api.rate_limit import limit_by_user
from app.models.website import Website
from app.models.workspace_member import WorkspaceMember
from app.services.jobs.kinds import FREQUENCY_INTERVALS, FREQUENCY_LABELS, KINDS
from app.services.jobs.schedules import schedule_views, upsert_schedule
from app.services.metrics.partitions import RETENTION_MONTHS
from app.services.metrics.registry import METRICS_BY_KEY, MetricDef
from app.services.metrics.series import (
    DEFAULT_RANGE_DAYS,
    MAX_RANGE_DAYS,
    Series,
    build_series,
    comparison_range,
    freshness,
    retention_floor,
)
from app.services.metrics.types import utc_now, utc_today
from app.services.workspaces import owned_website, require_owner

router = APIRouter(tags=["metrics"])

_GRANULARITIES = ("day", "week", "month")
_COMPARES = ("none", "previous_period", "previous_year")


# ---- séries temporelles -------------------------------------------------------
class SeriesPointOut(BaseModel):
    period_start: date
    period_end: date
    value: float | None
    days_covered: int
    days_expected: int


class SeriesBlockOut(BaseModel):
    start: date
    end: date
    total: float | None
    # Couverture du total : jours portant une valeur / jours de la fenêtre.
    days_covered: int
    days_expected: int
    points: list[SeriesPointOut]


class SeriesOut(BaseModel):
    metric: str
    label: str
    source: str
    unit: str
    direction: str
    granularity: str
    current: SeriesBlockOut
    comparison: SeriesBlockOut | None
    # Raison stable de l'absence de comparaison demandée (`hors_retention`), sinon null.
    comparison_unavailable: str | None = None
    last_collected_at: datetime | None
    data_until: date | None


@dataclass(frozen=True, slots=True)
class SeriesQuery:
    defn: MetricDef
    start: date
    end: date
    granularity: str
    compare: str


def _invalid(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=detail)


_OUT_OF_BOUNDS = "date hors limites"
_MIN_DAY = date(2000, 1, 1)


def _check_bounds(day: date, today: date) -> None:
    """Dates forgées (an 1, an 9999) : refusées avant tout calcul de fenêtre."""
    if day < _MIN_DAY or day > today + timedelta(days=366):
        raise _invalid(_OUT_OF_BOUNDS)


def parse_series_query(
    *,
    metric: str | None,
    start: str | None,
    end: str | None,
    granularity: str,
    compare: str,
    dimension: str | None = None,
    today: date,
) -> SeriesQuery:
    if not metric:
        raise _invalid("paramètre « metric » requis (par exemple ga4.sessions)")
    defn = METRICS_BY_KEY.get(metric)
    if defn is None:
        raise _invalid(f"métrique inconnue : {metric}")
    if dimension:
        raise _invalid("dimension non prise en charge (totaux du site uniquement)")
    if granularity not in _GRANULARITIES:
        raise _invalid("granularité invalide (day, week ou month)")
    if compare not in _COMPARES:
        raise _invalid("comparaison invalide (none, previous_period ou previous_year)")
    try:
        end_day = date.fromisoformat(end) if end else today - timedelta(days=1)
        _check_bounds(end_day, today)
        start_day = (
            date.fromisoformat(start) if start else end_day - timedelta(days=DEFAULT_RANGE_DAYS - 1)
        )
        _check_bounds(start_day, today)
    except OverflowError:
        raise _invalid(_OUT_OF_BOUNDS) from None
    except ValueError:
        raise _invalid("date invalide (format AAAA-MM-JJ)") from None
    if start_day > end_day:
        raise _invalid("la date de début doit précéder la date de fin")
    if (end_day - start_day).days + 1 > MAX_RANGE_DAYS:
        raise _invalid(f"période trop longue (au plus {MAX_RANGE_DAYS} jours)")
    if start_day < retention_floor(today):
        raise _invalid(
            f"période antérieure à la rétention des données ({RETENTION_MONTHS} mois)"
        )
    return SeriesQuery(defn, start_day, end_day, granularity, compare)


def _block(series: Series) -> SeriesBlockOut:
    return SeriesBlockOut(
        start=series.start,
        end=series.end,
        total=series.total,
        days_covered=series.days_covered,
        days_expected=series.days_expected,
        points=[
            SeriesPointOut(
                period_start=p.period_start,
                period_end=p.period_end,
                value=p.value,
                days_covered=p.days_covered,
                days_expected=p.days_expected,
            )
            for p in series.points
        ],
    )


@router.get(
    "/websites/{website_id}/metrics/series",
    response_model=SeriesOut,
    dependencies=[limit_by_user("metrics_read", limit=120, window=60)],
)
async def get_metric_series(
    website_id: UUID,
    user: CurrentUserDep,
    session: SessionDep,
    metric: Annotated[str | None, Query()] = None,
    start: Annotated[str | None, Query()] = None,
    end: Annotated[str | None, Query()] = None,
    granularity: Annotated[str, Query()] = "day",
    compare: Annotated[str, Query()] = "none",
    dimension: Annotated[str | None, Query()] = None,
) -> SeriesOut:
    # Appartenance d'abord : un étranger reçoit 404, jamais une erreur de paramètre.
    site = await owned_website(session, website_id=website_id, user_id=user.id)
    today = utc_today()
    query = parse_series_query(
        metric=metric, start=start, end=end, granularity=granularity, compare=compare,
        dimension=dimension, today=today,
    )
    try:
        current = await build_series(
            session, website_id=site.id, defn=query.defn, start=query.start, end=query.end,
            granularity=query.granularity,
        )
    except OverflowError:
        raise _invalid(_OUT_OF_BOUNDS) from None
    comparison = None
    unavailable = None
    if query.compare != "none":
        other = comparison_range(query.start, query.end, query.compare)
        if other is None or other[0] < retention_floor(today):
            # Un total sur une fenêtre en partie purgée serait un minorant non étiqueté.
            unavailable = "hors_retention"
        else:
            comparison = _block(
                await build_series(
                    session, website_id=site.id, defn=query.defn, start=other[0], end=other[1],
                    granularity=query.granularity,
                )
            )
    fresh = await freshness(session, site.id, query.defn.source)
    return SeriesOut(
        metric=query.defn.key,
        label=query.defn.label,
        source=query.defn.source,
        unit=query.defn.unit,
        direction=query.defn.direction,
        granularity=query.granularity,
        current=_block(current),
        comparison=comparison,
        comparison_unavailable=unavailable,
        last_collected_at=fresh.last_collected_at,
        data_until=fresh.data_until,
    )


# ---- planning (« Suivi automatique ») ------------------------------------------
class ScheduleOut(BaseModel):
    kind: str
    label: str
    frequency: str
    enabled: bool
    allowed_frequencies: list[str]
    floor_hours: int
    next_due_at: datetime | None
    last_run_at: datetime | None
    last_status: str | None
    last_success_at: datetime | None
    failing_since: datetime | None
    last_error_code: str | None
    # Texte français décidé par le code, prêt à afficher.
    last_error: str | None
    backfill_done_at: datetime | None


class SchedulesOut(BaseModel):
    website_id: UUID
    can_edit: bool
    frequency_labels: dict[str, str]
    schedules: list[ScheduleOut]


class SchedulePut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: str
    frequency: str
    enabled: bool = True

    @model_validator(mode="after")
    def _valid(self) -> Self:
        kind = KINDS.get(self.kind)
        if kind is None or not kind.schedulable:
            raise ValueError("type de suivi inconnu")
        if self.frequency not in FREQUENCY_INTERVALS:
            raise ValueError("fréquence inconnue")
        if self.frequency not in kind.allowed_frequencies():
            hours = int(kind.floor.total_seconds() // 3600)
            raise ValueError(
                f"fréquence trop élevée pour « {kind.label} » : au plus une fois toutes les {hours} h"
            )
        return self


async def _schedules_out(session, site: Website, user_id: UUID) -> SchedulesOut:
    role = await session.scalar(
        select(WorkspaceMember.role).where(
            WorkspaceMember.workspace_id == site.workspace_id, WorkspaceMember.user_id == user_id
        )
    )
    views = await schedule_views(session, site.id)
    return SchedulesOut(
        website_id=site.id,
        can_edit=role == "owner",
        frequency_labels=dict(FREQUENCY_LABELS),
        schedules=[
            ScheduleOut(
                kind=view.kind,
                label=view.label,
                frequency=view.frequency,
                enabled=view.enabled,
                allowed_frequencies=list(view.allowed_frequencies),
                floor_hours=view.floor_hours,
                next_due_at=view.next_due_at,
                last_run_at=view.last_run_at,
                last_status=view.last_status,
                last_success_at=view.last_success_at,
                failing_since=view.failing_since,
                last_error_code=view.last_error_code,
                last_error=view.last_error,
                backfill_done_at=view.backfill_done_at,
            )
            for view in views
        ],
    )


@router.get(
    "/websites/{website_id}/schedules",
    response_model=SchedulesOut,
    dependencies=[limit_by_user("schedules_read", limit=120, window=60)],
)
async def get_schedules(website_id: UUID, user: CurrentUserDep, session: SessionDep) -> SchedulesOut:
    site = await owned_website(session, website_id=website_id, user_id=user.id)
    return await _schedules_out(session, site, user.id)


@router.put(
    "/websites/{website_id}/schedules",
    response_model=SchedulesOut,
    dependencies=[limit_by_user("schedules_write", limit=30, window=60)],
)
async def put_schedule(
    website_id: UUID, body: SchedulePut, user: CurrentUserDep, session: SessionDep
) -> SchedulesOut:
    site = await owned_website(session, website_id=website_id, user_id=user.id)
    await require_owner(session, workspace_id=site.workspace_id, user_id=user.id)
    await upsert_schedule(
        session,
        website_id=site.id,
        kind=KINDS[body.kind],
        frequency=body.frequency,
        enabled=body.enabled,
        now=utc_now(),
    )
    await session.commit()
    return await _schedules_out(session, site, user.id)
