from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    environment: str = "local"

    database_url: str
    database_url_test: str
    database_url_migrations_test: str
    redis_url: str

    google_client_id: str = ""
    # SecretStr : masqué dans repr()/logs/traces (affiche '**********').
    # Lire la valeur avec .get_secret_value().
    google_client_secret: SecretStr = SecretStr("")
    google_oauth_redirect_uri: str = "http://localhost:8000/auth/google/callback"
    # true -> MockGoogleOAuthClient : aucun appel réseau, fixtures déterministes.
    google_oauth_mock: bool = False
    # true -> MockAuditProbe (fixtures). false -> RealAuditProbe (PageSpeed Insights).
    audit_probe_mock: bool = True
    # Clé PageSpeed Insights (optionnelle) : sans elle, appel keyless à quota
    # public limité ; sur échec -> mode dégradé (scores CWV à 0).
    pagespeed_api_key: SecretStr = SecretStr("")

    # --- Agent conseiller (advisor) ---
    # Clé API Anthropic. Vide OU advisor_mock=true -> MockAdvisorLLM (zéro réseau).
    anthropic_api_key: SecretStr = SecretStr("")
    advisor_mock: bool = True
    advisor_brief_model: str = "claude-opus-5"
    advisor_chat_model: str = "claude-sonnet-5"
    advisor_daily_brief_cap: int = 5
    advisor_daily_message_cap: int = 40  # incr. 3
    advisor_tool_iteration_cap: int = 6  # incr. 3

    # Où renvoyer le navigateur après le callback OAuth (défaut = dev front).
    frontend_base_url: str = "http://localhost:4000"
    session_cookie_name: str = "cc_session"
    # Origines autorisées par CORS (le front Next.js en dev).
    cors_origins: list[str] = [
        "http://127.0.0.1:4000",
        "http://localhost:4000",
    ]
    # Durée de vie d'une transaction OAuth (state + code_verifier) côté serveur.
    oauth_state_ttl_seconds: int = 600

    # {version:int -> clé base64 de 32 octets}. pydantic-settings parse le JSON
    # de la variable d'environnement automatiquement pour un type dict ; chaque
    # valeur est enveloppée en SecretStr (jamais en clair dans un repr/log).
    token_enc_keys: dict[int, SecretStr]
    token_enc_active_version: int

    app_secret_key: SecretStr


@lru_cache
def get_settings() -> Settings:
    return Settings()
