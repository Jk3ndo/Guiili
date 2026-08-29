"""Les secrets de configuration ne fuient pas en clair (repr / logs / traces)."""

from pydantic import SecretStr

from app.config import Settings

_BASE = {
    "database_url": "postgresql+asyncpg://u:p@h/db",
    "database_url_test": "postgresql+asyncpg://u:p@h/db",
    "database_url_migrations_test": "postgresql+asyncpg://u:p@h/db",
    "redis_url": "redis://h:6379/0",
    "token_enc_keys": {1: "a" * 44},
    "token_enc_active_version": 1,
    "app_secret_key": "TOP-SECRET-APP-KEY",
    "google_client_secret": "TOP-SECRET-GOOGLE",
}


def _settings(**overrides: object) -> Settings:
    return Settings(_env_file=None, **{**_BASE, **overrides})


def test_secret_fields_are_secretstr() -> None:
    s = _settings()
    assert isinstance(s.app_secret_key, SecretStr)
    assert isinstance(s.google_client_secret, SecretStr)
    assert all(isinstance(v, SecretStr) for v in s.token_enc_keys.values())


def test_repr_and_str_do_not_leak_secrets() -> None:
    s = _settings()
    for rendered in (repr(s), str(s)):
        assert "TOP-SECRET-APP-KEY" not in rendered
        assert "TOP-SECRET-GOOGLE" not in rendered
        assert "a" * 44 not in rendered


def test_secret_value_still_readable() -> None:
    s = _settings()
    assert s.app_secret_key.get_secret_value() == "TOP-SECRET-APP-KEY"
    assert s.google_client_secret.get_secret_value() == "TOP-SECRET-GOOGLE"
    assert s.token_enc_keys[1].get_secret_value() == "a" * 44
