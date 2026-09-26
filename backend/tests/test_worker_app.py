from datetime import UTC, datetime
from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.internal import get_headless_runner, get_job_services
from app.config import Settings, get_settings, worker_problems
from app.db.session import get_session
from app.main import app as api_app
from app.models.job_run import JobRun
from app.security.oidc import OidcVerifier
from app.services.gtm_headless import GtmHeadlessResult
from app.services.jobs.handlers import default_job_services
from app.services.jobs.health import FailingSchedule, JobsHealth
from app.services.metrics.types import Observation, SourceError, utc_now
from app.tools.jobs import main as jobs_main
from app.worker_main import create_worker_app
from tests.jobs_fakes import (
    SIGNING_KEY,
    TODAY,
    FakeSource,
    fake_services,
    google_id_token,
    jwks_for,
    make_site,
)

AUDIENCE = "https://worker.example.run.app"
CALLER = "guiili-tasks@guiili.iam.gserviceaccount.com"
INTERNAL_ROUTES = [
    ("POST", "/internal/tick", None),
    ("POST", "/internal/tasks/run", {"kind": "partition_maintenance", "window": "20260926"}),
    ("GET", "/internal/jobs/health", None),
    ("POST", "/internal/headless/verify", {"url": "https://exemple.fr"}),
]


def _sources(probe: FakeSource | None = None) -> dict[str, FakeSource]:
    unlinked = SourceError("not_linked", recoverable=False, not_applicable=True)
    return {
        "ga4": FakeSource("ga4", error=unlinked),
        "gsc": FakeSource("gsc", error=unlinked),
        "cwv": FakeSource("cwv"),
        "probe": probe or FakeSource("probe", [Observation("page_up", TODAY, 1.0)]),
    }


async def _fake_headless(url: str) -> GtmHeadlessResult:
    return GtmHeadlessResult(
        gtm_js_loaded=True, containers_initialised=("GTM-TEST",), datalayer_present=True,
        gtm_events=("gtm.js",), requests_before_consent=False, csp_console_errors=(),
        findings=(), checked_at=datetime(2026, 9, 26, tzinfo=UTC),
    )


def _auth(email: str = CALLER, **claims) -> dict[str, str]:
    return {"Authorization": f"Bearer {google_id_token(audience=AUDIENCE, email=email, **claims)}"}


@pytest_asyncio.fixture
async def worker_app(db_session: AsyncSession):
    async def fetch_jwks() -> dict:
        return jwks_for(SIGNING_KEY)

    verifier = OidcVerifier(audience=AUDIENCE, allowed_emails={CALLER}, fetch_jwks=fetch_jwks)
    application = create_worker_app(get_settings(), oidc_verifier=verifier)

    async def _session():
        yield db_session

    application.dependency_overrides[get_session] = _session
    application.dependency_overrides[get_job_services] = lambda: fake_services(_sources())
    application.dependency_overrides[get_headless_runner] = lambda: _fake_headless
    return application


@pytest_asyncio.fixture
async def worker(worker_app):
    async with AsyncClient(transport=ASGITransport(app=worker_app), base_url="http://w") as client:
        yield client


def test_the_public_api_exposes_no_internal_route() -> None:
    assert not any(getattr(route, "path", "").startswith("/internal") for route in api_app.routes)
    assert not any(path.startswith("/internal") for path in api_app.openapi()["paths"])


@pytest.mark.parametrize(("method", "path", "body"), INTERNAL_ROUTES)
async def test_internal_routes_require_a_google_identity(worker, method, path, body) -> None:
    anonymous = await worker.request(method, path, json=body)
    assert anonymous.status_code == 401
    wrong_audience = await worker.request(
        method, path, json=body,
        headers={"Authorization": "Bearer " + google_id_token(audience="https://x", email=CALLER)},
    )
    assert wrong_audience.status_code == 401
    stranger = await worker.request(method, path, json=body, headers=_auth("intrus@example.com"))
    assert stranger.status_code == 403


async def test_a_tick_runs_the_due_tasks_inline(
    worker, db_session: AsyncSession, make_user
) -> None:
    site = await make_site(db_session, make_user, "worker-tick.test")
    resp = await worker.post("/internal/tick", headers=_auth())
    assert resp.status_code == 200, resp.text
    assert resp.json()["enqueued"] == 6
    runs = {
        run.kind + ":" + run.params.get("source", ""): run.status
        for run in (
            await db_session.execute(select(JobRun).where(JobRun.website_id == site.id))
        ).scalars()
    }
    assert runs == {
        "backfill:ga4": "skipped",
        "backfill:gsc": "skipped",
        "collect_cwv:": "succeeded",
        "collect_probes:": "succeeded",
        "measurement_check:": "succeeded",
    }


@pytest.mark.parametrize(
    ("body", "fragment"),
    [
        ({"kind": "inconnu", "window": "w"}, "type de tâche inconnu"),
        ({"kind": "collect_probes", "window": "w"}, "site et workspace"),
        ({"kind": "partition_maintenance", "window": "w", "website_id": str(uuid4()),
          "workspace_id": str(uuid4())}, "tâche globale"),
        ({"kind": "partition_maintenance", "window": "w w"}, "fenêtre invalide"),
        ({"kind": "backfill", "window": "w", "website_id": str(uuid4()),
          "workspace_id": str(uuid4()), "params": {"source": "cwv"}}, "source de rattrapage"),
        ({"kind": "partition_maintenance", "window": "w", "params": {"x": "y"}}, "paramètres"),
        ({"kind": "partition_maintenance", "window": "w", "extra": 1}, "extra"),
    ],
)
async def test_the_run_payload_is_strictly_validated(worker, body: dict, fragment: str) -> None:
    resp = await worker.post("/internal/tasks/run", json=body, headers=_auth())
    assert resp.status_code == 422
    assert fragment in resp.text


async def test_a_recoverable_failure_asks_cloud_tasks_to_retry(
    worker, worker_app, db_session: AsyncSession, make_user
) -> None:
    site = await make_site(db_session, make_user, "worker-retry.test")
    failing = FakeSource("probe", error=SourceError("unreachable", recoverable=True))
    worker_app.dependency_overrides[get_job_services] = lambda: fake_services(_sources(failing))
    body = {"kind": "collect_probes", "window": "w", "website_id": str(site.id),
            "workspace_id": str(site.workspace_id)}
    resp = await worker.post("/internal/tasks/run", json=body, headers=_auth())
    assert resp.status_code == 503 and resp.headers["Retry-After"] == "60"
    assert resp.json() == {"claim": "claimed", "status": "failed"}


async def test_a_run_for_a_mismatched_workspace_is_refused(
    worker, db_session: AsyncSession, make_user
) -> None:
    site = await make_site(db_session, make_user, "worker-mismatch.test")
    body = {"kind": "collect_probes", "window": "w", "website_id": str(site.id),
            "workspace_id": str(uuid4())}
    resp = await worker.post("/internal/tasks/run", json=body, headers=_auth())
    assert resp.status_code == 422


async def test_a_run_for_a_deleted_site_is_acknowledged(worker) -> None:
    body = {"kind": "collect_probes", "window": "w", "website_id": str(uuid4()),
            "workspace_id": str(uuid4())}
    resp = await worker.post("/internal/tasks/run", json=body, headers=_auth())
    assert resp.status_code == 200 and resp.json() == {"claim": "gone", "status": None}


async def test_the_health_summary_is_served(worker) -> None:
    resp = await worker.get("/internal/jobs/health", headers=_auth())
    assert resp.status_code == 200
    assert resp.json()["ok"] is True and resp.json()["failing"] == []


async def test_headless_runs_only_for_a_known_https_site(
    worker, db_session: AsyncSession, make_user
) -> None:
    await make_site(db_session, make_user, "worker-headless.test")
    unknown = await worker.post(
        "/internal/headless/verify", json={"url": "https://inconnu.test"}, headers=_auth()
    )
    assert unknown.status_code == 404
    plain = await worker.post(
        "/internal/headless/verify", json={"url": "http://worker-headless.test"}, headers=_auth()
    )
    assert plain.status_code == 422
    ok = await worker.post(
        "/internal/headless/verify", json={"url": "https://worker-headless.test"}, headers=_auth()
    )
    assert ok.status_code == 200 and ok.json()["containers_initialised"] == ["GTM-TEST"]


_STAGING = {
    "environment": "staging",
    # Les arguments priment sur l'environnement du processus (conftest force
    # GOOGLE_OAUTH_MOCK=true, interdit hors local).
    "google_oauth_mock": False,
    "database_url": "postgresql+asyncpg://u:p@h/db",
    "token_enc_keys": {1: "A" * 43 + "="},
    "token_enc_active_version": 1,
    "app_secret_key": "x" * 40,
    "frontend_base_url": "https://app.example.com",
    "cors_origins": ["https://app.example.com"],
}
_WORKER = {
    "task_queue_backend": "cloud_tasks",
    "gcp_project": "guiili",
    "cloud_tasks_location": "us-central1",
    "tasks_invoker_service_account": CALLER,
    "worker_base_url": AUDIENCE,
    "internal_oidc_audience": AUDIENCE,
    "internal_allowed_invokers": [CALLER],
}


def test_worker_problems_name_missing_settings_without_values() -> None:
    assert worker_problems(get_settings()) == []  # local
    problems = worker_problems(Settings(_env_file=None, **_STAGING))
    text = " ".join(problems)
    for name in ("TASK_QUEUE_BACKEND", "GCP_PROJECT", "WORKER_BASE_URL", "INTERNAL_ALLOWED_INVOKERS"):
        assert name in text
    assert worker_problems(Settings(_env_file=None, **_STAGING, **_WORKER)) == []


def test_an_incomplete_worker_refuses_to_start_outside_local() -> None:
    with pytest.raises(RuntimeError, match="worker"):
        create_worker_app(Settings(_env_file=None, **_STAGING))


def test_the_local_tick_tool_refuses_other_environments(capsys: pytest.CaptureFixture[str]) -> None:
    assert jobs_main(["jobs"]) == 2
    assert jobs_main(["jobs", "tick"], settings=Settings(_env_file=None, **_STAGING, **_WORKER)) == 2
    assert "local" in capsys.readouterr().err


async def test_a_rejected_payload_is_not_echoed(worker) -> None:
    secret = "valeur-secrete-1234"
    resp = await worker.post(
        "/internal/tasks/run",
        json={"kind": "partition_maintenance", "window": "w", "params": {"token": secret}},
        headers=_auth(),
    )
    assert resp.status_code == 422
    assert secret not in resp.text and "input" not in resp.text


async def test_a_failing_tick_answers_503_without_leaking_the_error(
    worker, worker_app, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def broken(*args, **kwargs):
        raise RuntimeError("postgres://u:motdepasse@h/db")

    monkeypatch.setattr("app.api.internal.tick", broken)
    resp = await worker.post("/internal/tick", headers=_auth())
    assert resp.status_code == 503
    assert "motdepasse" not in resp.text and "motdepasse" not in caplog.text
    assert any(getattr(r, "event", "") == "tick_failed" for r in caplog.records)


async def test_the_health_failing_list_is_bounded(
    worker, monkeypatch: pytest.MonkeyPatch
) -> None:
    since = datetime(2026, 9, 1, tzinfo=UTC)
    items = tuple(
        FailingSchedule(uuid4(), "collect_probes", since, "unreachable", True) for _ in range(150)
    )

    async def fake_health(session, *, now):
        return JobsHealth(checked_at=now, failing=items, overdue=0, stuck_running=0, stuck_queued=0)

    monkeypatch.setattr("app.api.internal.compute_jobs_health", fake_health)
    body = (await worker.get("/internal/jobs/health", headers=_auth())).json()
    assert body["ok"] is False and len(body["failing"]) == 100 and body["failing_total"] == 150


def test_the_default_services_share_one_clock_and_need_no_network() -> None:
    services = default_job_services(get_settings())
    assert services.now is utc_now
