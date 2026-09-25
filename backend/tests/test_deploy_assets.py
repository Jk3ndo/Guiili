import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from app.tools.check_env import validate_env

ROOT = Path(__file__).resolve().parents[2]
BASH = shutil.which("bash")

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
    "TOKEN_ENC_KEYS": '{"1":"' + "a" * 44 + '"}',
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
