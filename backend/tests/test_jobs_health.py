import logging
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.job_run import JobRun
from app.models.schedule import Schedule
from app.services.jobs.health import (
    CLIENT_ACTION_CODES,
    FAILING_AFTER,
    MAINTENANCE_STALE_AFTER,
    OVERDUE_AFTER,
    STUCK_QUEUED_AFTER,
    STUCK_RUNNING_GRACE,
    FailingSchedule,
    JobsHealth,
    compute_jobs_health,
    report_jobs_health,
)
from app.services.jobs.messages import ERROR_MESSAGES, error_message
from app.services.metrics.sources.google_http import RECOVERABLE_REASONS
from tests.jobs_fakes import make_site

NOW = datetime(2026, 9, 26, 6, 0, tzinfo=UTC)


def _schedule(site, kind: str, **values) -> Schedule:
    base = {"website_id": site.id, "kind": kind, "frequency": "daily", "enabled": True,
            "next_due_at": NOW + timedelta(hours=1)}
    base.update(values)
    return Schedule(**base)


def _run(site, key: str, **values) -> JobRun:
    base = {"idempotency_key": key, "kind": "collect_probes", "website_id": site.id,
            "workspace_id": site.workspace_id, "window_label": "w", "params": {},
            "status": "queued", "attempt": 0, "max_attempts": 5, "observations": 0,
            "enqueued_at": NOW}
    base.update(values)
    return JobRun(**base)


async def test_a_collection_failing_for_more_than_a_day_is_reported(
    db_session: AsyncSession, make_user
) -> None:
    site = await make_site(db_session, make_user, "health-fail.test")
    db_session.add_all(
        [
            _schedule(site, "collect_gsc", failing_since=NOW - timedelta(hours=25),
                      last_error_code="quota"),
            _schedule(site, "collect_ga4", failing_since=NOW - timedelta(hours=25),
                      last_error_code="token_unavailable"),
            _schedule(site, "collect_cwv", failing_since=NOW - timedelta(hours=2),
                      last_error_code="quota"),
        ]
    )
    await db_session.flush()
    health = await compute_jobs_health(db_session, now=NOW)
    kinds = {f.kind: f.client_action for f in health.failing}
    assert kinds == {"collect_gsc": False, "collect_ga4": True}
    assert [f.kind for f in health.internal_failures] == ["collect_gsc"]
    assert not health.ok


async def test_archived_sites_and_disabled_schedules_are_ignored(
    db_session: AsyncSession, make_user
) -> None:
    site = await make_site(db_session, make_user, "health-archived.test")
    site.archived_at = NOW
    other = await make_site(db_session, make_user, "health-disabled.test")
    db_session.add_all(
        [
            _schedule(site, "collect_gsc", failing_since=NOW - timedelta(days=3)),
            _schedule(other, "collect_gsc", enabled=False, failing_since=NOW - timedelta(days=3),
                      next_due_at=NOW - timedelta(days=3)),
        ]
    )
    await db_session.flush()
    health = await compute_jobs_health(db_session, now=NOW)
    assert health.ok and health.failing == () and health.overdue == 0


async def test_overdue_and_stuck_runs_are_counted(db_session: AsyncSession, make_user) -> None:
    site = await make_site(db_session, make_user, "health-stuck.test")
    db_session.add_all(
        [
            _schedule(site, "collect_probes", next_due_at=NOW - timedelta(hours=3)),
            _run(site, "a", status="running", lease_expires_at=NOW - timedelta(minutes=6)),
            _run(site, "b", status="running", lease_expires_at=NOW + timedelta(minutes=10)),
            _run(site, "c", status="queued", enqueued_at=NOW - timedelta(hours=2)),
            _run(site, "d", status="queued", enqueued_at=NOW - timedelta(minutes=5)),
        ]
    )
    await db_session.flush()
    health = await compute_jobs_health(db_session, now=NOW)
    assert (health.overdue, health.stuck_running, health.stuck_queued) == (1, 1, 1)


def _health(**values) -> JobsHealth:
    base = {"checked_at": NOW, "failing": (), "overdue": 0, "stuck_running": 0, "stuck_queued": 0}
    base.update(values)
    return JobsHealth(**base)


def _failing(client_action: bool) -> FailingSchedule:
    return FailingSchedule(
        website_id=None, kind="collect_gsc", failing_since=NOW - timedelta(days=2),
        error_code="token_unavailable" if client_action else "quota", client_action=client_action,
    )


def test_a_healthy_report_is_info_without_sentry(caplog: pytest.LogCaptureFixture) -> None:
    captured: list = []
    with caplog.at_level(logging.INFO, logger="app.services.jobs.health"):
        report_jobs_health(_health(), capture=lambda message, extra: captured.append(message))
    assert captured == []
    assert any(r.message == "jobs_health_ok" for r in caplog.records)


def test_our_failures_are_errors_sent_to_sentry(caplog: pytest.LogCaptureFixture) -> None:
    captured: list = []
    with caplog.at_level(logging.INFO, logger="app.services.jobs.health"):
        report_jobs_health(
            _health(failing=(_failing(False), _failing(True)), stuck_queued=2),
            capture=lambda message, extra: captured.append((message, extra)),
        )
    record = next(r for r in caplog.records if r.message == "jobs_health_alert")
    assert record.levelno == logging.ERROR
    assert record.event == "jobs_health_alert"
    assert (record.failing_internal, record.failing_client_action, record.stuck_queued) == (1, 1, 2)
    assert captured == [
        (
            "Tâches planifiées en échec ou en retard",
            {"failing_internal": 1, "failing_client_action": 1, "overdue": 0,
             "stuck_running": 0, "stuck_queued": 2, "maintenance_stale": False,
             "kinds": ["collect_gsc"]},
        )
    ]


def test_client_side_failures_only_are_warnings(caplog: pytest.LogCaptureFixture) -> None:
    captured: list = []
    with caplog.at_level(logging.INFO, logger="app.services.jobs.health"):
        report_jobs_health(_health(failing=(_failing(True),)), capture=lambda m, e: captured.append(m))
    record = next(r for r in caplog.records if r.message == "jobs_health_alert")
    assert record.levelno == logging.WARNING and captured == []


def test_error_messages_are_french_and_never_empty() -> None:
    assert error_message(None) is None
    assert error_message("quota").startswith("Quota Google atteint")
    assert error_message("code-inconnu") == "Erreur inattendue : nous sommes prévenus."


def test_every_error_code_the_code_can_produce_has_a_french_message() -> None:
    produced = set(RECOVERABLE_REASONS) | {
        "db_transient", "api_key_rejected", "token_refresh_failed", "truncated", "bad_request",
        "job_lease_lost", "lease_expired", "not_dispatched", "enqueue_failed", "internal_error",
        "site_unreachable", "unreachable", "ga4_not_connected", "gsc_not_connected",
    }
    assert produced <= set(ERROR_MESSAGES)
    assert all(text.strip() for text in ERROR_MESSAGES.values())


_CLIENT_WORDING = ("reconnecte", "ton site", "Ton site")


def test_label_and_classification_agree_for_every_code() -> None:
    """Un libellé qui s'adresse au client n'existe que pour un code côté client, et
    inversement : sinon un site client hors ligne alerterait l'équipe en permanence."""
    assert {
        "token_unavailable",
        "permission_or_api_disabled",
        "not_found",
        "site_unreachable",
        "unreachable",
    } == CLIENT_ACTION_CODES
    assert set(ERROR_MESSAGES) >= CLIENT_ACTION_CODES
    for code, text in ERROR_MESSAGES.items():
        if code in CLIENT_ACTION_CODES:
            # Le client peut agir : le libellé ne dit pas « nous sommes prévenus ».
            assert "prévenus" not in text, code
        else:
            assert not any(word in text for word in _CLIENT_WORDING), code


def test_unknown_or_missing_codes_fail_loud_on_the_operator_side() -> None:
    assert "code-inconnu" not in CLIENT_ACTION_CODES
    assert None not in CLIENT_ACTION_CODES
    assert error_message("unknown_kind") == error_message("bad_params")
    assert error_message("unknown_kind") == "Erreur inattendue : nous sommes prévenus."


async def test_unknown_and_missing_error_codes_are_operator_failures(
    db_session: AsyncSession, make_user
) -> None:
    site = await make_site(db_session, make_user, "health-unknown.test")
    since = NOW - timedelta(days=2)
    db_session.add_all(
        [
            _schedule(site, "collect_gsc", failing_since=since, last_error_code=None),
            _schedule(site, "collect_ga4", failing_since=since, last_error_code="code-inconnu"),
            _schedule(site, "collect_probes", failing_since=since, last_error_code="unreachable"),
        ]
    )
    await db_session.flush()
    health = await compute_jobs_health(db_session, now=NOW)
    assert {f.kind: f.client_action for f in health.failing} == {
        "collect_gsc": False,
        "collect_ga4": False,
        "collect_probes": True,
    }
    assert sorted(f.kind for f in health.internal_failures) == ["collect_ga4", "collect_gsc"]


async def test_thresholds_are_exact_at_their_boundaries(
    db_session: AsyncSession, make_user
) -> None:
    site = await make_site(db_session, make_user, "health-bounds.test")
    other = await make_site(db_session, make_user, "health-bounds2.test")
    db_session.add_all(
        [
            # Exactement 24 h : compté ; 24 h moins une seconde : pas encore.
            _schedule(site, "collect_gsc", failing_since=NOW - FAILING_AFTER, last_error_code="quota"),
            _schedule(
                other, "collect_gsc",
                failing_since=NOW - FAILING_AFTER + timedelta(seconds=1), last_error_code="quota",
            ),
            # Exactement 2 h de retard : pas compté ; 2 h et une seconde : compté.
            _schedule(site, "collect_probes", next_due_at=NOW - OVERDUE_AFTER),
            _schedule(other, "collect_probes", next_due_at=NOW - OVERDUE_AFTER - timedelta(seconds=1)),
            _run(site, "q1", status="queued", enqueued_at=NOW - STUCK_QUEUED_AFTER),
            _run(site, "q2", status="queued", enqueued_at=NOW - STUCK_QUEUED_AFTER - timedelta(seconds=1)),
            _run(site, "r1", status="running", lease_expires_at=NOW - STUCK_RUNNING_GRACE),
            _run(
                site, "r2", status="running",
                lease_expires_at=NOW - STUCK_RUNNING_GRACE - timedelta(seconds=1),
            ),
        ]
    )
    await db_session.flush()
    health = await compute_jobs_health(db_session, now=NOW)
    assert [f.website_id for f in health.failing] == [site.id]
    assert (health.overdue, health.stuck_queued, health.stuck_running) == (1, 1, 1)


async def test_a_running_job_without_a_lease_is_stuck_and_archived_sites_still_count(
    db_session: AsyncSession, make_user
) -> None:
    site = await make_site(db_session, make_user, "health-nolease.test")
    site.archived_at = NOW
    db_session.add(_run(site, "n1", status="running", lease_expires_at=None))
    await db_session.flush()
    health = await compute_jobs_health(db_session, now=NOW)
    # `stuck_*` inclut les job_runs de sites archivés (contrairement à failing/overdue).
    assert health.stuck_running == 1 and not health.ok


async def test_a_rejected_api_key_is_an_operator_error(
    db_session: AsyncSession, make_user
) -> None:
    site = await make_site(db_session, make_user, "health-key.test")
    db_session.add(
        _schedule(site, "collect_cwv", failing_since=NOW - timedelta(days=2),
                  last_error_code="api_key_rejected")
    )
    await db_session.flush()
    health = await compute_jobs_health(db_session, now=NOW)
    assert [f.client_action for f in health.failing] == [False]


def test_alerts_carry_only_codes_and_counts(caplog: pytest.LogCaptureFixture) -> None:
    captured: list = []
    with caplog.at_level(logging.INFO, logger="app.services.jobs.health"):
        report_jobs_health(
            _health(failing=(_failing(False),), overdue=1),
            capture=lambda message, extra: captured.append((message, extra)),
        )
    record = next(r for r in caplog.records if r.message == "jobs_health_alert")
    extras = {k: v for k, v in record.__dict__.items() if k.startswith(("failing", "stuck", "overdue", "kinds"))}
    for value in [*extras.values(), *captured[0][1].values()]:
        assert isinstance(value, (int, list))
        if isinstance(value, list):
            assert all(isinstance(item, str) for item in value)
    assert record.exc_info is None


def test_a_failing_sentry_capture_never_breaks_the_report(
    caplog: pytest.LogCaptureFixture,
) -> None:
    def boom(message: str, extra: dict) -> None:
        raise RuntimeError("secret-dsn-value")

    with caplog.at_level(logging.INFO, logger="app.services.jobs.health"):
        report_jobs_health(_health(overdue=1), capture=boom)
    failure = next(r for r in caplog.records if r.message == "jobs_health_capture_failed")
    assert failure.levelno == logging.WARNING and failure.error_type == "RuntimeError"
    assert "secret-dsn-value" not in caplog.text


def _maintenance(site, key: str, **values) -> JobRun:
    base = {"kind": "partition_maintenance", "website_id": None, "workspace_id": None,
            "status": "succeeded", "attempt": 1, "finished_at": NOW}
    base.update(values)
    return _run(site, key, **base)


async def test_a_stale_partition_maintenance_is_reported(
    db_session: AsyncSession, make_user
) -> None:
    site = await make_site(db_session, make_user, "health-maint.test")
    db_session.add_all(
        [
            _maintenance(site, "m-old", finished_at=NOW - MAINTENANCE_STALE_AFTER - timedelta(hours=1)),
            _run(site, "recent", status="succeeded", enqueued_at=NOW - timedelta(hours=1)),
        ]
    )
    await db_session.flush()
    health = await compute_jobs_health(db_session, now=NOW)
    assert health.maintenance_stale and not health.ok


async def test_a_recent_or_failed_partition_maintenance(
    db_session: AsyncSession, make_user
) -> None:
    site = await make_site(db_session, make_user, "health-maint2.test")
    db_session.add(_maintenance(site, "m-ok", finished_at=NOW - timedelta(hours=20)))
    await db_session.flush()
    assert not (await compute_jobs_health(db_session, now=NOW)).maintenance_stale
    # Un échec plus récent ne compte pas comme un succès : le dernier succès date de 60 h.
    later = NOW + timedelta(hours=40)
    assert (await compute_jobs_health(db_session, now=later)).maintenance_stale


async def test_a_missing_partition_maintenance_is_reported_only_after_48_hours(
    db_session: AsyncSession, make_user
) -> None:
    site = await make_site(db_session, make_user, "health-maint3.test")
    # Aucune tâche du tout : rien à signaler.
    assert not (await compute_jobs_health(db_session, now=NOW)).maintenance_stale
    db_session.add(_run(site, "first", status="succeeded", enqueued_at=NOW - timedelta(hours=47)))
    await db_session.flush()
    assert not (await compute_jobs_health(db_session, now=NOW)).maintenance_stale
    assert (await compute_jobs_health(db_session, now=NOW + timedelta(hours=2))).maintenance_stale


def test_a_stale_maintenance_is_an_operator_alert(caplog: pytest.LogCaptureFixture) -> None:
    captured: list = []
    with caplog.at_level(logging.INFO, logger="app.services.jobs.health"):
        report_jobs_health(
            _health(maintenance_stale=True),
            capture=lambda message, extra: captured.append(message),
        )
    record = next(r for r in caplog.records if r.message == "jobs_health_alert")
    assert record.levelno == logging.ERROR and record.maintenance_stale is True
    assert captured == ["Tâches planifiées en échec ou en retard"]
