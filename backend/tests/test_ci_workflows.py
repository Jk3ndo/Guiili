from pathlib import Path

import pytest
import yaml

WORKFLOWS = Path(__file__).resolve().parents[2] / ".github" / "workflows"


def _load(name: str) -> dict:
    data = yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8"))
    # PyYAML lit la clé « on » comme le booléen True.
    if True in data:
        data["on"] = data.pop(True)
    return data


def _steps(job: dict) -> str:
    return "\n".join(str(step.get("run", "")) + str(step.get("uses", "")) for step in job["steps"])


def test_ci_runs_on_pull_requests_and_main_with_read_only_permissions() -> None:
    ci = _load("ci.yml")
    assert "pull_request" in ci["on"] and "push" in ci["on"]
    assert "pull_request_target" not in ci["on"]
    assert ci["permissions"] == {"contents": "read"}
    assert ci["concurrency"]["cancel-in-progress"] is True


def test_backend_job_checks_lint_migrations_and_tests_against_postgres() -> None:
    job = _load("ci.yml")["jobs"]["backend"]
    assert "postgres" in job["services"]
    body = _steps(job)
    assert "ruff check" in body
    assert "alembic upgrade head" in body and "alembic check" in body
    assert "pytest -W error" in body
    assert "control_center_test" in body and "control_center_migrations" in body
    env = job["env"]
    assert env["ENVIRONMENT"] == "local"
    assert env["GOOGLE_OAUTH_MOCK"] == "true"


def test_frontend_job_lints_and_builds_with_zero_warnings() -> None:
    job = _load("ci.yml")["jobs"]["frontend"]
    body = _steps(job)
    assert "npm ci" in body and "npm run lint" in body and "npm run build" in body


def test_dependabot_covers_backend_frontend_and_actions() -> None:
    config = yaml.safe_load(
        (WORKFLOWS.parent / "dependabot.yml").read_text(encoding="utf-8")
    )
    ecosystems = {update["package-ecosystem"] for update in config["updates"]}
    assert {"uv", "npm", "github-actions"} <= ecosystems


@pytest.mark.parametrize("name", ["ci.yml", "deploy-staging.yml"])
def test_no_workflow_hardcodes_a_secret(name: str) -> None:
    path = WORKFLOWS / name
    if not path.exists():
        pytest.skip("workflow ajouté à la tâche 8")
    text = path.read_text(encoding="utf-8")
    assert "AIza" not in text and "sk-ant" not in text and "BEGIN PRIVATE KEY" not in text


def test_deploy_staging_is_manual_and_restricted_to_main() -> None:
    workflow = _load("deploy-staging.yml")
    assert list(workflow["on"]) == ["workflow_dispatch"]
    job = workflow["jobs"]["deploy"]
    assert job["if"] == "github.ref == 'refs/heads/main'"
    assert job["environment"] == "staging"
