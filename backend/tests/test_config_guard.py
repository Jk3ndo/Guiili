import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError

from app.config import Settings, get_settings
from app.logging_config import configure_logging
from app.main import create_app


@pytest.fixture(autouse=True)
def _restore_logging():
    yield
    configure_logging(get_settings())


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
        ({"worker_base_url": "http://worker.internal"}, "WORKER_BASE_URL"),
    ],
)
def test_production_rejects_unsafe_settings(override: dict, fragment: str) -> None:
    with pytest.raises(ValidationError) as excinfo:
        _settings(_PROD, **override)
    assert fragment in str(excinfo.value)


def test_worker_url_is_free_locally_and_https_when_deployed() -> None:
    # Local : repli sur le navigateur local ou worker de développement en http.
    assert _settings(_LOCAL, worker_base_url="http://127.0.0.1:8030").worker_base_url
    assert _settings(_PROD, worker_base_url="").worker_base_url == ""
    deployed = _settings(_PROD, worker_base_url="https://worker.example.run.app")
    assert deployed.worker_base_url.startswith("https://")


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


_LEAKY_SECRET = "ZZ-secret-value-must-never-appear-" + "q" * 20


def test_validation_error_never_echoes_input_values(monkeypatch: pytest.MonkeyPatch) -> None:
    # Hermétique : la CI fournit DATABASE_URL par l'environnement, qui comblerait le champ retiré.
    monkeypatch.delenv("DATABASE_URL", raising=False)
    # Règle de production violée : la valeur (secret) ne doit pas figurer dans str(exc),
    # qui finit dans les traces uvicorn et les logs du Job de migration.
    with pytest.raises(ValidationError) as rule_violation:
        _settings(_PROD, google_oauth_mock=True, app_secret_key=_LEAKY_SECRET[:10])
    assert "input_value" not in str(rule_violation.value)
    assert _LEAKY_SECRET[:10] not in str(rule_violation.value)

    # Champ obligatoire manquant : Pydantic affiche sinon le dict d'entrée complet.
    incomplete = {k: v for k, v in _PROD.items() if k != "database_url"}
    with pytest.raises(ValidationError) as missing:
        _settings(incomplete, app_secret_key=_LEAKY_SECRET)
    assert "input_value" not in str(missing.value)
    assert _LEAKY_SECRET not in str(missing.value)
    assert "database_url" in str(missing.value).lower()
