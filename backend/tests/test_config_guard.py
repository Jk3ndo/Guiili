import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError

from app.config import Settings
from app.main import create_app

_LOCAL = {
    "database_url": "postgresql+asyncpg://u:p@h/prod",
    "database_url_test": "postgresql+asyncpg://u:p@h/prod",
    "database_url_migrations_test": "postgresql+asyncpg://u:p@h/prod",
    "redis_url": "redis://h:6379/0",
    "token_enc_keys": {1: "a" * 44},
    "token_enc_active_version": 1,
    "app_secret_key": "x" * 40,
}
_PROD = {
    **_LOCAL,
    "environment": "production",
    "google_oauth_mock": False,
    "audit_probe_mock": False,
    "advisor_mock": False,
    "frontend_base_url": "https://app.example.com",
    "cors_origins": ["https://app.example.com"],
}


def _settings(base: dict, **overrides: object) -> Settings:
    return Settings(_env_file=None, **{**base, **overrides})


def test_local_accepts_mocks_and_short_secrets() -> None:
    s = _settings(_LOCAL, google_oauth_mock=True, app_secret_key="short")
    assert s.environment == "local"
    assert s.database_url_test != ""


def test_valid_production_passes_and_ignores_test_databases() -> None:
    s = _settings(_PROD)
    assert s.environment == "production"
    # Une base de test qui pointe sur la vraie base est neutralisée, pas fatale.
    assert s.database_url_test == ""
    assert s.database_url_migrations_test == ""


@pytest.mark.parametrize(
    ("override", "fragment"),
    [
        ({"google_oauth_mock": True}, "GOOGLE_OAUTH_MOCK"),
        ({"app_secret_key": "court"}, "APP_SECRET_KEY"),
        ({"app_secret_key": "REMPLACER" + "x" * 40}, "APP_SECRET_KEY"),
        ({"frontend_base_url": "http://app.example.com"}, "FRONTEND_BASE_URL"),
        ({"cors_origins": ["http://localhost:4000"]}, "CORS_ORIGINS"),
        ({"audit_probe_mock": True}, "AUDIT_PROBE_MOCK"),
        ({"advisor_mock": True}, "ADVISOR_MOCK"),
    ],
)
def test_production_rejects_unsafe_settings(override: dict, fragment: str) -> None:
    with pytest.raises(ValidationError) as excinfo:
        _settings(_PROD, **override)
    assert fragment in str(excinfo.value)


def test_staging_tolerates_probe_and_advisor_mocks() -> None:
    s = _settings(_PROD, environment="staging", audit_probe_mock=True, advisor_mock=True)
    assert s.environment == "staging"


def test_unknown_environment_is_rejected() -> None:
    with pytest.raises(ValidationError):
        _settings(_LOCAL, environment="prod")


def test_derived_flags_follow_the_environment() -> None:
    local = _settings(_LOCAL)
    prod = _settings(_PROD)
    assert local.json_logs is False and local.api_docs_enabled is True
    assert prod.json_logs is True and prod.api_docs_enabled is False
    assert _settings(_PROD, log_json=False).json_logs is False
    assert _settings(_PROD, enable_api_docs=True).api_docs_enabled is True


async def test_docs_are_hidden_in_production_but_health_stays_up() -> None:
    app = create_app(_settings(_PROD))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        for path in ("/docs", "/redoc", "/openapi.json"):
            assert (await client.get(path)).status_code == 404, path
        assert (await client.get("/health")).status_code == 200


async def test_docs_are_served_locally() -> None:
    app = create_app(_settings(_LOCAL))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        assert (await client.get("/openapi.json")).status_code == 200
