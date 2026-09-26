from datetime import UTC, date, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.metric_point import MetricPoint
from app.models.schedule import Schedule
from app.models.user import User
from app.models.website import Website
from app.models.workspace_member import WorkspaceMember
from app.services.jobs.kinds import KINDS
from app.services.jobs.schedules import upsert_schedule
from app.services.metrics.store import store_observations
from app.services.metrics.types import Observation, utc_now, utc_today
from tests.conftest import owner_workspace_id


async def _own_site(db_session: AsyncSession, user: User, domain: str) -> Website:
    workspace_id = await owner_workspace_id(db_session, user)
    site = Website(workspace_id=workspace_id, domain=domain, display_name=domain)
    db_session.add(site)
    await db_session.flush()
    return site


async def _member_site(db_session: AsyncSession, make_user, user: User, domain: str) -> Website:
    owner = await make_user(sub=f"owner-{domain}")
    site = await _own_site(db_session, owner, domain)
    db_session.add(WorkspaceMember(workspace_id=site.workspace_id, user_id=user.id, role="member"))
    await db_session.flush()
    return site


async def test_series_returns_the_stored_values(
    authed_client: tuple[AsyncClient, User], db_session: AsyncSession
) -> None:
    client, user = authed_client
    site = await _own_site(db_session, user, "api-series.test")
    yesterday = utc_today() - timedelta(days=1)
    await store_observations(
        db_session, website_id=site.id, source="ga4",
        observations=[Observation("sessions", yesterday, 42.0)], run_id=None, now=utc_now(),
    )
    resp = await client.get(
        f"/api/v1/websites/{site.id}/metrics/series",
        params={"metric": "ga4.sessions", "compare": "previous_period"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["metric"] == "ga4.sessions" and body["unit"] == "count"
    assert body["current"]["end"] == yesterday.isoformat()
    assert len(body["current"]["points"]) == 28
    assert body["current"]["points"][-1]["value"] == 42.0
    assert body["current"]["points"][0]["value"] is None
    assert body["current"]["total"] == 42.0
    assert body["comparison"]["total"] is None
    assert body["data_until"] == yesterday.isoformat()


@pytest.mark.parametrize(
    ("params", "fragment"),
    [
        ({}, "metric"),
        ({"metric": "ga4.inconnue"}, "métrique inconnue"),
        ({"metric": "ga4.sessions", "granularity": "year"}, "granularité"),
        ({"metric": "ga4.sessions", "compare": "hier"}, "comparaison"),
        ({"metric": "ga4.sessions", "start": "26/09/2026"}, "date invalide"),
        ({"metric": "ga4.sessions", "start": "2026-09-20", "end": "2026-09-01"}, "début"),
        ({"metric": "ga4.sessions", "start": "2020-01-01", "end": "2026-01-01"}, "trop longue"),
    ],
)
async def test_series_parameters_are_validated_in_french(
    authed_client: tuple[AsyncClient, User], db_session: AsyncSession, params: dict, fragment: str
) -> None:
    client, user = authed_client
    site = await _own_site(db_session, user, "api-series-422.test")
    resp = await client.get(f"/api/v1/websites/{site.id}/metrics/series", params=params)
    assert resp.status_code == 422
    assert fragment in resp.json()["detail"]


async def test_schedules_list_the_five_kinds_with_defaults(
    authed_client: tuple[AsyncClient, User], db_session: AsyncSession
) -> None:
    client, user = authed_client
    site = await _own_site(db_session, user, "api-sched.test")
    resp = await client.get(f"/api/v1/websites/{site.id}/schedules")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["can_edit"] is True
    kinds = {s["kind"]: s for s in body["schedules"]}
    assert list(kinds) == [
        "collect_ga4", "collect_gsc", "collect_cwv", "collect_probes", "measurement_check",
    ]
    assert kinds["collect_ga4"]["frequency"] == "daily"
    assert kinds["collect_ga4"]["allowed_frequencies"] == [
        "three_daily", "daily", "every_3_days", "weekly",
    ]
    assert kinds["collect_probes"]["floor_hours"] == 1
    assert kinds["collect_probes"]["next_due_at"] is None
    assert body["frequency_labels"]["hourly"] == "Toutes les heures"


async def test_the_owner_changes_a_schedule(
    authed_client: tuple[AsyncClient, User], db_session: AsyncSession
) -> None:
    client, user = authed_client
    site = await _own_site(db_session, user, "api-sched-put.test")
    resp = await client.put(
        f"/api/v1/websites/{site.id}/schedules",
        json={"kind": "collect_probes", "frequency": "hourly", "enabled": False},
    )
    assert resp.status_code == 200, resp.text
    probes = next(s for s in resp.json()["schedules"] if s["kind"] == "collect_probes")
    assert (probes["frequency"], probes["enabled"]) == ("hourly", False)
    row = await db_session.scalar(select(Schedule).where(Schedule.website_id == site.id))
    assert row.kind == "collect_probes" and row.enabled is False


@pytest.mark.parametrize(
    ("body", "fragment"),
    [
        ({"kind": "collect_ga4", "frequency": "hourly"}, "fréquence trop élevée"),
        ({"kind": "backfill", "frequency": "daily"}, "type de suivi inconnu"),
        ({"kind": "collect_ga4", "frequency": "monthly"}, "fréquence inconnue"),
        ({"kind": "collect_ga4", "frequency": "daily", "extra": True}, "extra"),
    ],
)
async def test_invalid_schedule_bodies_are_refused(
    authed_client: tuple[AsyncClient, User], db_session: AsyncSession, body: dict, fragment: str
) -> None:
    client, user = authed_client
    site = await _own_site(db_session, user, "api-sched-422.test")
    resp = await client.put(f"/api/v1/websites/{site.id}/schedules", json=body)
    assert resp.status_code == 422
    assert fragment in resp.text


async def test_a_member_reads_but_cannot_change_schedules(
    authed_client: tuple[AsyncClient, User], db_session: AsyncSession, make_user
) -> None:
    client, user = authed_client
    site = await _member_site(db_session, make_user, user, "api-sched-member.test")
    read = await client.get(f"/api/v1/websites/{site.id}/schedules")
    assert read.status_code == 200 and read.json()["can_edit"] is False
    write = await client.put(
        f"/api/v1/websites/{site.id}/schedules",
        json={"kind": "collect_probes", "frequency": "weekly", "enabled": True},
    )
    assert write.status_code == 403
    assert await db_session.scalar(select(func.count()).select_from(Schedule)) == 0


async def test_purging_a_site_deletes_its_series_and_schedules(
    authed_client: tuple[AsyncClient, User], db_session: AsyncSession
) -> None:
    client, user = authed_client
    site = await _own_site(db_session, user, "api-purge.test")
    await store_observations(
        db_session, website_id=site.id, source="ga4",
        observations=[Observation("sessions", date(2026, 9, 20), 1.0)], run_id=None,
        now=utc_now(),
    )
    await client.put(
        f"/api/v1/websites/{site.id}/schedules",
        json={"kind": "collect_ga4", "frequency": "daily", "enabled": True},
    )
    resp = await client.delete(f"/api/v1/websites/{site.id}", params={"purge": "true"})
    assert resp.status_code == 204
    db_session.expunge_all()
    assert await db_session.scalar(select(func.count()).select_from(MetricPoint)) == 0
    assert await db_session.scalar(select(func.count()).select_from(Schedule)) == 0


async def test_tightening_a_schedule_pulls_the_due_date_forward_but_never_into_the_past(
    db_session: AsyncSession, make_user
) -> None:
    owner = await make_user(sub="owner-upsert")
    site = await _own_site(db_session, owner, "api-upsert.test")
    kind = KINDS["collect_probes"]
    now = datetime(2026, 9, 26, 12, 0, tzinfo=UTC)
    row = await upsert_schedule(
        db_session, website_id=site.id, kind=kind, frequency="weekly", enabled=True, now=now
    )
    row.last_run_at = datetime(2026, 9, 26, 6, 0, tzinfo=UTC)
    row.next_due_at = datetime(2026, 10, 3, 6, 0, tzinfo=UTC)
    await db_session.flush()
    row = await upsert_schedule(
        db_session, website_id=site.id, kind=kind, frequency="hourly", enabled=True, now=now
    )
    # dernier passage + 1 h serait dans le passé : l'échéance devient « maintenant ».
    assert row.frequency == "hourly" and row.next_due_at == now
    # Un relâchement de fréquence ne repousse jamais une échéance déjà plus proche.
    row = await upsert_schedule(
        db_session, website_id=site.id, kind=kind, frequency="weekly", enabled=False, now=now
    )
    assert row.next_due_at == now and row.enabled is False
