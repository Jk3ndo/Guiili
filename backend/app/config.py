from functools import lru_cache
from typing import Literal, Self

from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", hide_input_in_errors=True)

    environment: Literal["local", "staging", "production"] = "local"

    database_url: str
    # Bases jetables des tests. Vides et ignorées hors `local` : elles n'ont aucun
    # sens en déploiement, et une base de test qui pointerait sur la vraie base
    # serait détruite par `drop_all`.
    database_url_test: str = ""
    database_url_migrations_test: str = ""
    redis_url: str = ""

    google_client_id: str = ""
    # SecretStr : masqué dans repr()/logs/traces (affiche '**********').
    # Lire la valeur avec .get_secret_value().
    google_client_secret: SecretStr = SecretStr("")
    google_oauth_redirect_uri: str = "http://127.0.0.1:8020/api/v1/auth/google/callback"
    # Redirect URI du flow de connexion de DONNEES (GA4/GSC), distinct du login
    # ci-dessus : chaque flow a son propre callback et Google exige que le
    # redirect_uri soit le meme a l'autorisation et a l'echange de code.
    google_data_redirect_uri: str = "http://127.0.0.1:8020/api/v1/connections/google/callback"
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
    frontend_base_url: str = "http://127.0.0.1:4000"
    session_cookie_name: str = "cc_session"
    # Origines autorisées par CORS (le front Next.js en dev).
    cors_origins: list[str] = [
        "http://127.0.0.1:4000",
        "http://localhost:4000",
    ]
    # Durée de vie d'une transaction OAuth (state + code_verifier) côté serveur.
    oauth_state_ttl_seconds: int = 600

    # --- Exploitation ---
    # None -> JSON hors local (Cloud Logging), texte lisible en local.
    log_json: bool | None = None
    # DSN Sentry ; vide -> suivi d'erreurs désactivé.
    sentry_dsn: SecretStr = SecretStr("")
    sentry_traces_sample_rate: float = 0.0
    # None -> /docs, /redoc et /openapi.json exposés en local uniquement.
    enable_api_docs: bool | None = None
    # Limitation de débit des routes sensibles (voir app/api/rate_limit.py).
    rate_limit_enabled: bool = True

    # {version:int -> clé base64 de 32 octets}. pydantic-settings parse le JSON
    # de la variable d'environnement automatiquement pour un type dict ; chaque
    # valeur est enveloppée en SecretStr (jamais en clair dans un repr/log).
    token_enc_keys: dict[int, SecretStr]
    token_enc_active_version: int

    app_secret_key: SecretStr

    @property
    def json_logs(self) -> bool:
        return self.log_json if self.log_json is not None else self.environment != "local"

    @property
    def api_docs_enabled(self) -> bool:
        if self.enable_api_docs is not None:
            return self.enable_api_docs
        return self.environment == "local"

    @model_validator(mode="after")
    def _enforce_environment_rules(self) -> Self:
        if self.environment == "local":
            return self
        self.database_url_test = ""
        self.database_url_migrations_test = ""

        problems: list[str] = []
        if self.google_oauth_mock:
            problems.append("GOOGLE_OAUTH_MOCK doit être false (les routes /dev seraient exposées)")
        secret = self.app_secret_key.get_secret_value()
        if len(secret) < 32 or secret.upper().startswith("REMPLACER"):
            problems.append("APP_SECRET_KEY : au moins 32 caractères, valeur réelle")
        if not self.frontend_base_url.startswith("https://"):
            problems.append("FRONTEND_BASE_URL doit commencer par https://")
        if any(not origin.startswith("https://") for origin in self.cors_origins):
            problems.append("CORS_ORIGINS ne doit contenir que des origines https://")
        if self.environment == "production":
            if self.audit_probe_mock:
                problems.append("AUDIT_PROBE_MOCK doit être false (données factices sinon)")
            if self.advisor_mock:
                problems.append("ADVISOR_MOCK doit être false (réponses factices sinon)")
        if problems:
            raise ValueError(
                f"Configuration invalide pour ENVIRONMENT={self.environment} : "
                + " ; ".join(problems)
            )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
