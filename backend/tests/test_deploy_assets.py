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
    result = subprocess.run([str(BASH), "-n", str(path)], capture_output=True, text=True, check=False)
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
