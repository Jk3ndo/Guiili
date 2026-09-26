import logging
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.job_run import JobRun
from app.models.schedule import Schedule
from app.services.jobs.health import (
    CLIENT_ACTION_CODES,
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
            _run(site, "a", status="running", lease_expires_at=NOW - timedelta(minutes=1)),
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
             "stuck_running": 0, "stuck_queued": 2, "kinds": ["collect_gsc"]},
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


def test_operator_side_codes_never_ask_the_client_to_act() -> None:
    for code in ("db_transient", "api_key_rejected", "token_refresh_failed", "truncated",
                 "bad_request", "quota", "network", "api_error", "lease_expired",
                 "job_lease_lost", "not_dispatched", "internal_error"):
        assert code not in CLIENT_ACTION_CODES
        text = error_message(code) or ""
        assert "reconnecte" not in text and "Ton site" not in text and "ton site" not in text
    assert {"token_unavailable", "permission_or_api_disabled", "not_found",
            "site_unreachable"} == CLIENT_ACTION_CODES


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
