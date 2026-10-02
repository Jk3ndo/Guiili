import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from app.tools.check_env import main, validate_env

ROOT = Path(__file__).resolve().parents[2]
BASH = shutil.which("bash")

_GOOD_KEY = "A" * 43 + "="  # 32 octets une fois décodée (base64 valide)

_VALID = {
    "ENVIRONMENT": "production",
    "DATABASE_URL": "postgresql+asyncpg://u:p@h/db",
    "GOOGLE_CLIENT_ID": "id",
    "GOOGLE_CLIENT_SECRET": "secret",
    "GOOGLE_OAUTH_REDIRECT_URI": "https://app.example.com/api/v1/auth/google/callback",
    "GOOGLE_DATA_REDIRECT_URI": "https://app.example.com/api/v1/connections/google/callback",
    "GOOGLE_OAUTH_MOCK": "false",
    "AUDIT_PROBE_MOCK": "false",
    "ADVISOR_MOCK": "false",
    "FRONTEND_BASE_URL": "https://app.example.com",
    "CORS_ORIGINS": '["https://app.example.com"]',
    "TOKEN_ENC_KEYS": '{"1":"' + _GOOD_KEY + '"}',
    "TOKEN_ENC_ACTIVE_VERSION": "1",
    "APP_SECRET_KEY": "x" * 48,
}


def test_dockerfile_no_longer_migrates_at_startup() -> None:
    dockerfile = (ROOT / "backend" / "Dockerfile").read_text(encoding="utf-8")
    cmd_lines = [line for line in dockerfile.splitlines() if line.startswith("CMD")]
    assert cmd_lines, "CMD introuvable"
    assert all("alembic" not in line for line in cmd_lines)
    assert any("uvicorn" in line for line in cmd_lines)


@pytest.mark.skipif(BASH is None, reason="bash indisponible")
@pytest.mark.parametrize("script", ["deploy-backend.sh", "export-service-env.sh"])
def test_scripts_have_valid_bash_syntax(script: str) -> None:
    path = ROOT / "scripts" / script
    assert path.exists()
    # Chemin absolu : sous Windows, `bash` seul se résout vers le shim WSL de System32.
    result = subprocess.run(
        [str(BASH), "-n", str(path)], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr


def test_example_env_file_is_valid_and_secret_free() -> None:
    example = yaml.safe_load((ROOT / "deploy" / "env.example.yaml").read_text(encoding="utf-8"))
    assert validate_env({k: str(v) for k, v in example.items()}) == []
    for value in example.values():
        assert "AIza" not in str(value) and "sk-ant" not in str(value)


def test_real_env_files_are_git_ignored() -> None:
    ignored = (ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "deploy/env.*.yaml" in ignored
    assert "!deploy/env.example.yaml" in ignored


def test_validate_env_accepts_a_complete_production_file() -> None:
    assert validate_env(dict(_VALID)) == []


@pytest.mark.parametrize(
    ("mutation", "fragment"),
    [
        ({"GOOGLE_OAUTH_MOCK": "true"}, "GOOGLE_OAUTH_MOCK"),
        ({"APP_SECRET_KEY": "court"}, "APP_SECRET_KEY"),
        ({"ENVIRONMENT": "prod"}, "environment"),
    ],
)
def test_validate_env_reports_unsafe_values(mutation: dict, fragment: str) -> None:
    problems = validate_env({**_VALID, **mutation})
    assert problems and any(fragment.lower() in p.lower() for p in problems)


def test_validate_env_reports_missing_required_keys() -> None:
    incomplete = {k: v for k, v in _VALID.items() if k not in {"DATABASE_URL", "APP_SECRET_KEY"}}
    problems = " ".join(validate_env(incomplete)).lower()
    assert "database_url" in problems and "app_secret_key" in problems


def test_validate_env_ignores_the_process_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://leak/leak")
    incomplete = {k: v for k, v in _VALID.items() if k != "DATABASE_URL"}
    assert validate_env(incomplete) != []


@pytest.mark.parametrize(
    ("mutation", "fragment"),
    [
        ({"AUDIT_PROBE_MOCK": "true"}, "AUDIT_PROBE_MOCK"),
        ({"ADVISOR_MOCK": "true"}, "ADVISOR_MOCK"),
        ({"FRONTEND_BASE_URL": "http://app.example.com"}, "FRONTEND_BASE_URL"),
    ],
)
def test_validate_env_enforces_production_only_rules(mutation: dict, fragment: str) -> None:
    problems = validate_env({**_VALID, **mutation})
    assert any(fragment in p for p in problems)


_SECRET = "s3cr3t-" + "k" * 41  # 48 caractères : valide, mais à ne jamais divulguer
_DB_PASSWORD = "hunter2-db-password"
_SECRET_MAPPING = {
    **_VALID,
    "APP_SECRET_KEY": _SECRET,
    "DATABASE_URL": f"postgresql+asyncpg://u:{_DB_PASSWORD}@h/db",
}


@pytest.mark.parametrize(
    "mapping",
    [
        # champ obligatoire manquant (DATABASE_URL absent, secrets présents)
        {k: v for k, v in _SECRET_MAPPING.items() if k != "DATABASE_URL"},
        # valeur dangereuse (mock activé) alors que les secrets sont présents
        {**_SECRET_MAPPING, "GOOGLE_OAUTH_MOCK": "true"},
        # secret trop court : sa valeur ne doit pas être citée
        {**_SECRET_MAPPING, "APP_SECRET_KEY": "court-mais-secret"},
    ],
    ids=["champ-manquant", "valeur-dangereuse", "secret-court"],
)
def test_validate_env_never_leaks_secret_values(mapping: dict) -> None:
    problems = validate_env(mapping)
    assert problems
    text = "\n".join(problems)
    for value in (_SECRET, _DB_PASSWORD, "court-mais-secret", "secret", "input_value"):
        assert value not in text
    assert "errors.pydantic.dev" not in text


def test_validate_env_reports_malformed_json_without_echoing_it() -> None:
    problems = validate_env({**_SECRET_MAPPING, "TOKEN_ENC_KEYS": "{pas-du-json-" + _SECRET})
    assert problems
    assert _SECRET not in "\n".join(problems)


@pytest.mark.skipif(BASH is None, reason="bash indisponible")
@pytest.mark.parametrize(
    "args", [["production", "--dryrun"], ["production", "-n"], ["staging", "--dry_run"]]
)
def test_deploy_script_rejects_unknown_option_before_any_action(args: list[str]) -> None:
    result = subprocess.run(
        [str(BASH), str(ROOT / "scripts" / "deploy-backend.sh"), *args],
        capture_output=True,
        text=True,
        check=False,
        # PATH vide de gcloud : si le garde-fou échouait, on ne toucherait à rien.
        env={"PATH": str(Path(str(BASH)).parent)},
    )
    assert result.returncode == 2, result.stdout + result.stderr
    assert "usage" in result.stderr.lower()
    assert "== 1/5" not in result.stdout


@pytest.mark.skipif(BASH is None, reason="bash indisponible")
def test_deploy_script_rejects_extra_arguments() -> None:
    result = subprocess.run(
        [str(BASH), str(ROOT / "scripts" / "deploy-backend.sh"), "staging", "--dry-run", "x"],
        capture_output=True,
        text=True,
        check=False,
        env={"PATH": str(Path(str(BASH)).parent)},
    )
    assert result.returncode == 2, result.stdout + result.stderr
    assert "== 1/5" not in result.stdout


# --- Coherence ENVIRONMENT / cible du deploiement (--expect) -------------------------------


def test_validate_env_expect_accepts_a_matching_environment() -> None:
    assert validate_env(dict(_VALID), expect="production") == []


def test_validate_env_expect_rejects_another_environment() -> None:
    problems = validate_env({**_VALID, "ENVIRONMENT": "staging"}, expect="production")
    assert any("ENVIRONMENT" in p and "production" in p for p in problems)


def test_validate_env_expect_rejects_a_missing_environment() -> None:
    # Sans ENVIRONMENT, Settings retombe sur `local` et toutes les regles de production
    # sont sautees : c'est le cas dangereux que --expect doit attraper.
    problems = validate_env({k: v for k, v in _VALID.items() if k != "ENVIRONMENT"}, expect="production")
    assert any("ENVIRONMENT" in p and "production" in p for p in problems)


def _write_env(tmp_path: Path, data: dict) -> str:
    path = tmp_path / "env.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return str(path)


def test_main_expect_flag(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = _write_env(tmp_path, _VALID)
    assert main(["check_env", path, "--expect", "production"]) == 0
    assert main(["check_env", path, "--expect", "staging"]) == 1
    assert "ENVIRONMENT" in capsys.readouterr().err
    assert main(["check_env", path, "--expect"]) == 2
    assert main(["check_env", path, "--expect", "prod"]) == 2


def test_deploy_script_calls_check_env_with_its_target() -> None:
    script = (ROOT / "scripts" / "deploy-backend.sh").read_text(encoding="utf-8")
    assert '--expect "$ENVIRONMENT_NAME"' in script


# --- Cles de chiffrement des tokens ---------------------------------------------------------


@pytest.mark.parametrize(
    ("keys", "fragment"),
    [
        ('{"2":"' + _GOOD_KEY + '"}', "version active 1"),  # active (1) absente du registre
        ('{"1":"pas du base64 !!"}', "base64"),
        ('{"1":"' + "a" * 44 + '"}', "33 octets"),  # base64 valide mais pas 32 octets
    ],
    ids=["version-active-absente", "non-base64", "longueur-incorrecte"],
)
def test_validate_env_rejects_broken_token_keys(keys: str, fragment: str) -> None:
    problems = validate_env({**_VALID, "TOKEN_ENC_KEYS": keys})
    assert any(fragment in p for p in problems), problems
    assert "a" * 44 not in " ".join(problems)
    assert "pas du base64" not in " ".join(problems)


# --- Valeurs non textuelles (gcloud --env-vars-file exige des chaines) -------------------------


@pytest.mark.parametrize("bad", [True, 42, None, 1.5, ["x"]], ids=repr)
def test_main_rejects_non_string_values_naming_the_key(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], bad: object
) -> None:
    path = _write_env(tmp_path, {**_VALID, "ADVISOR_MOCK": bad})
    assert main(["check_env", path]) == 1
    err = capsys.readouterr().err
    assert "ADVISOR_MOCK" in err and "chaîne" in err


def test_main_non_string_error_never_prints_the_value(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = _write_env(tmp_path, {**_VALID, "APP_SECRET_KEY": 123456789})
    assert main(["check_env", path]) == 1
    err = capsys.readouterr().err
    assert "APP_SECRET_KEY" in err and "123456789" not in err


def test_validate_env_parses_the_internal_invokers_list_as_json() -> None:
    invokers = '["guiili-tasks@guiili.iam.gserviceaccount.com"]'
    assert validate_env({**_VALID, "INTERNAL_ALLOWED_INVOKERS": invokers}) == []


def test_validate_env_accepts_the_optional_per_route_invoker_lists() -> None:
    invokers = '["guiili-tasks@guiili.iam.gserviceaccount.com"]'
    optional = {
        "INTERNAL_SCHEDULER_INVOKERS": invokers,
        "INTERNAL_TASKS_INVOKERS": invokers,
        "INTERNAL_HEADLESS_INVOKERS": invokers,
    }
    assert validate_env({**_VALID, **optional}) == []


# --- Lot B : deux images, deux services, service worker ---------------------------------

_WORKER_ENV = {
    "TASK_QUEUE_BACKEND": "cloud_tasks",
    "GCP_PROJECT": "guiili",
    "CLOUD_TASKS_LOCATION": "us-central1",
    "CLOUD_TASKS_QUEUE_PREFIX": "guiili",
    "TASKS_INVOKER_SERVICE_ACCOUNT": "guiili-tasks@guiili.iam.gserviceaccount.com",
    "WORKER_BASE_URL": "https://backend-guiili-worker-1.us-central1.run.app",
    "INTERNAL_OIDC_AUDIENCE": "https://backend-guiili-worker-1.us-central1.run.app",
    "INTERNAL_ALLOWED_INVOKERS": '["guiili-tasks@guiili.iam.gserviceaccount.com"]',
}


def test_the_api_image_has_no_browser_and_the_worker_image_does() -> None:
    api = (ROOT / "backend" / "Dockerfile").read_text(encoding="utf-8")
    worker = (ROOT / "backend" / "Dockerfile.worker").read_text(encoding="utf-8")
    assert "playwright install" not in api
    assert "playwright install --with-deps chromium" in worker
    worker_cmd = [line for line in worker.splitlines() if line.startswith("CMD")]
    assert worker_cmd and "app.worker_main:app" in worker_cmd[0]
    assert "alembic" not in worker_cmd[0]


def test_the_worker_build_config_uses_the_worker_dockerfile() -> None:
    config = yaml.safe_load((ROOT / "backend" / "cloudbuild.worker.yaml").read_text(encoding="utf-8"))
    args = config["steps"][0]["args"]
    assert args[:3] == ["build", "-f", "Dockerfile.worker"]
    assert "$_IMAGE" in args and config["images"] == ["$_IMAGE"]


def test_the_example_env_file_is_valid_for_the_worker() -> None:
    example = yaml.safe_load((ROOT / "deploy" / "env.example.yaml").read_text(encoding="utf-8"))
    assert validate_env({k: str(v) for k, v in example.items()}, service="worker") == []


def test_validate_env_names_missing_worker_settings_without_values() -> None:
    problems = validate_env({**_VALID}, service="worker")
    text = " ".join(problems)
    assert "WORKER_BASE_URL" in text and "INTERNAL_ALLOWED_INVOKERS" in text
    assert validate_env({**_VALID, **_WORKER_ENV}, service="worker") == []
    # Le contrôle par défaut (API) n'exige rien de nouveau.
    assert validate_env({**_VALID}) == []


def test_main_service_flag(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = _write_env(tmp_path, {**_VALID, **_WORKER_ENV})
    assert main(["check_env", path, "--service", "worker", "--expect", "production"]) == 0
    assert main(["check_env", path, "--expect", "production", "--service", "worker"]) == 0
    assert main(["check_env", path, "--service", "cron"]) == 2
    incomplete = _write_env(tmp_path, dict(_VALID))
    assert main(["check_env", incomplete, "--service", "worker"]) == 1
    assert "WORKER_BASE_URL" in capsys.readouterr().err


@pytest.mark.skipif(BASH is None, reason="bash indisponible")
def test_the_dry_run_builds_and_deploys_both_services(tmp_path: Path) -> None:
    env_file = tmp_path / "env.staging.yaml"
    env_file.write_text(
        yaml.safe_dump({**_VALID, **_WORKER_ENV, "ENVIRONMENT": "staging"}), encoding="utf-8"
    )
    result = subprocess.run(
        [str(BASH), str(ROOT / "scripts" / "deploy-backend.sh"), "staging", "--dry-run"],
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "DEPLOY_ENV_FILE": env_file.as_posix()},
    )
    assert result.returncode == 0, result.stdout + result.stderr
    out = result.stdout
    for step in ("== 1/5", "== 2/5", "== 3/5", "== 4/5", "== 5/5"):
        assert step in out
    assert "cloudbuild.worker.yaml" in out and "_IMAGE=" in out
    assert "gcloud run deploy backend-guiili-staging --image" in out
    assert "gcloud run deploy backend-guiili-staging-worker --image" in out
    worker_line = next(
        line for line in out.splitlines() if "run deploy backend-guiili-staging-worker" in line
    )
    assert "--no-allow-unauthenticated" in worker_line and "--memory 2Gi" in worker_line
    for option in (
        "--max-instances 2",
        "--concurrency 10",
        "--timeout 900",
        "--service-account backend-guiili-staging-worker@guiili.iam.gserviceaccount.com",
    ):
        assert option in worker_line, option
    api_line = next(
        line
        for line in out.splitlines()
        if "run deploy backend-guiili-staging --image" in line
    )
    assert "--allow-unauthenticated" in api_line and "--no-allow-unauthenticated" not in api_line
    # Ordre : images -> migration -> worker -> API (l'API ne doit jamais etre en ligne
    # avant le worker auquel elle delegue la verification headless).
    order = [
        out.index("builds submit"),
        out.index("cloudbuild.worker.yaml"),
        out.index("run jobs deploy backend-guiili-staging-migrate"),
        out.index("run deploy backend-guiili-staging-worker"),
        out.index("run deploy backend-guiili-staging --image"),
    ]
    assert order == sorted(order) and len(set(order)) == len(order)
    assert "(dry-run" in out


def test_the_deploy_script_checks_the_worker_configuration() -> None:
    script = (ROOT / "scripts" / "deploy-backend.sh").read_text(encoding="utf-8")
    assert "--service worker" in script
    assert "DEPLOY_ENV_FILE" in script
    # Jeton lu une fois avant la boucle de verification, jamais de Bearer vide.
    assert 'TOKEN="$(gcloud auth print-identity-token)" ||' in script
    assert "Bearer $(gcloud" not in script
