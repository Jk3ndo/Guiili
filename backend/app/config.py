from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    environment: str = "local"

    database_url: str
    database_url_test: str
    database_url_migrations_test: str
    redis_url: str

    google_client_id: str = ""
    google_client_secret: str = ""
    google_oauth_redirect_uri: str = "http://localhost:8000/auth/google/callback"

    # {version:int -> clé base64 de 32 octets}. pydantic-settings parse le JSON
    # de la variable d'environnement automatiquement pour un type dict.
    token_enc_keys: dict[int, str]
    token_enc_active_version: int

    app_secret_key: str


@lru_cache
def get_settings() -> Settings:
    return Settings()
