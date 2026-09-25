# Lot 0 : socle de production — plan d'exécution

> **Pour les agents d'exécution :** SOUS-COMPÉTENCE OBLIGATOIRE : utiliser
> superpowers:subagent-driven-development (recommandé) ou
> superpowers:executing-plans pour exécuter ce plan tâche par tâche. Les étapes
> utilisent la syntaxe à cases (`- [ ]`) pour le suivi.

**Objectif :** rendre l'application exploitable en production par plusieurs
clients : configuration qui refuse de démarrer mal réglée, logs corrélables, erreurs
suivies, abus freinés, isolation entre clients prouvée par des tests, CI sur chaque
PR, migrations hors démarrage, déploiement scripté et documenté.

**Architecture :** aucun changement fonctionnel visible. On ajoute des modules
transverses (`logging_config`, `observability`, `security/rate_limit`), on
factorise la création de l'application (`create_app`), on retire la migration du
démarrage du conteneur au profit d'un Cloud Run Job, et on ajoute une CI GitHub
Actions et un script de déploiement.

**Stack :** FastAPI / Starlette 1.6, pydantic-settings, SQLAlchemy 2, Alembic,
sentry-sdk (optionnel), GitHub Actions, Cloud Run + Cloud Run Jobs, Neon.

**Spec :** `docs/superpowers/specs/2026-09-25-roadmap-v3-architecture-design.md`
(§3, §6 et §8, lot 0). Les faits de production sur lesquels ce plan s'appuie sont
dans « État constaté en production » ci-dessous.

## État constaté en production (2026-09-25)

Lu en lecture seule sur le service Cloud Run `backend-guiili` (région `us-central1`,
projet `guiili`, 512 Mo, `maxScale` 3, concurrence 80) :

- `ENVIRONMENT=production`, `GOOGLE_OAUTH_MOCK=false`, `AUDIT_PROBE_MOCK=false`,
  `ADVISOR_MOCK=false`. `APP_SECRET_KEY` fait 64 caractères.
- **Tous les secrets sont des variables d'environnement en clair** ; Secret Manager
  n'est pas activé. Aucun Cloud Run Job n'existe.
- **`DATABASE_URL_TEST` et `DATABASE_URL_MIGRATIONS_TEST` sont réglées sur la base de
  production** (mêmes valeurs que `DATABASE_URL`). Un `pytest` lancé avec cet
  environnement exécuterait `drop_all` sur la production. `REDIS_URL` pointe sur
  `localhost` (inutilisé).
- Le conteneur exécute `alembic upgrade head` à chaque démarrage, avec jusqu'à 3
  instances : deux migrations peuvent se lancer en même temps.
- Il n'y a ni dossier `.github`, ni logs structurés, ni suivi d'erreurs, ni limitation
  de débit. Le dépôt distant est `github.com/Jk3ndo/Guiili`.

## Contraintes globales (valables pour toutes les tâches)

- **Aucun changement de comportement fonctionnel** : les 394+ tests existants restent
  verts sans modification (hors ajouts explicitement listés).
- **Aucune action sur la production, aucun push, aucun déploiement** pendant
  l'exécution du plan. Les étapes marquées **[PROPRIÉTAIRE]** sont manuelles et
  réservées à l'utilisateur ; l'exécutant les liste dans son compte rendu sans les
  faire.
- **Aucun secret dans le dépôt** : les fichiers `deploy/env.<env>.yaml` sont ignorés
  par git, seul `deploy/env.example.yaml` (valeurs factices) est versionné.
- **Rien de sensible dans les logs ni dans Sentry** : jamais de chaîne de requête, de
  corps de requête, de cookie, d'en-tête d'autorisation, de code OAuth, de jeton.
- **Qualité** : `cd backend && .venv/Scripts/python.exe -m pytest -W error -q` vert
  (deux passages identiques), `uv run ruff check app tests` propre, `alembic check`
  propre. Si `uv` n'est pas dans le PATH : `"$APPDATA/Python/Python312/Scripts/uv.exe"`.
- Tests : fixtures de `backend/tests/conftest.py` (`authed_client`, `db_session`,
  `make_user`, `owner_workspace_id`), aucun appel réseau, jamais de vrai Chromium.
- Conventions git : branche `feat/production-foundation`, un commit par tâche,
  messages en français, jamais de `--no-verify`, jamais de push.
- Textes destinés aux utilisateurs (erreurs d'API) en français.

## Structure des fichiers

Backend (nouveaux) : `app/logging_config.py`, `app/observability.py`,
`app/security/rate_limit.py`, `app/api/rate_limit.py`, `app/tools/__init__.py`,
`app/tools/check_env.py`, `tests/db_safety.py`.
Backend (modifiés) : `app/config.py`, `app/main.py`, `app/api/v1/endpoints/{auth,
connections,websites,audit,advisor}.py`, `tests/conftest.py`,
`tests/test_migrations.py`, `tests/test_enum_check_constraints.py`, `Dockerfile`,
`pyproject.toml`, `uv.lock`.
Tests (nouveaux) : `test_config_guard.py`, `test_db_safety.py`,
`test_logging_config.py`, `test_observability.py`, `test_rate_limit.py`,
`test_rate_limit_endpoints.py`, `test_tenant_isolation.py`,
`test_deploy_assets.py`, `test_ci_workflows.py`.
Racine : `.github/workflows/{ci.yml,deploy-staging.yml}`, `.github/dependabot.yml`,
`scripts/{deploy-backend.sh,export-service-env.sh}`, `deploy/env.example.yaml`,
`docs/ops/runbook.md`, `.gitignore`.

## Ordre des tâches

1 Configuration par environnement et sécurité des bases de test → 2 Logs JSON et
identifiant de requête → 3 Suivi d'erreurs → 4 Limitation de débit → 5 Suite
d'isolation entre clients → 6 Migrations hors démarrage et déploiement scripté →
7 CI GitHub Actions → 8 Runbook, préproduction et déploiement continu → 9
Vérification finale.

---

### Tâche 1 : Configuration par environnement et sécurité des bases de test

**Fichiers :**
- Modifier : `backend/app/config.py`, `backend/app/main.py`
- Créer : `backend/tests/db_safety.py`
- Modifier : `backend/tests/conftest.py`, `backend/tests/test_migrations.py`,
  `backend/tests/test_enum_check_constraints.py`
- Test : `backend/tests/test_config_guard.py`, `backend/tests/test_db_safety.py`

**Interfaces :**
- Produit : `Settings.environment: Literal["local","staging","production"]`,
  `Settings.json_logs`, `Settings.api_docs_enabled` (propriétés), champs
  `log_json`, `sentry_dsn`, `sentry_traces_sample_rate`, `enable_api_docs`,
  `rate_limit_enabled` ; `create_app(settings=None) -> FastAPI` dans `app.main`
  (`app` reste l'instance par défaut) ; `assert_safe_test_database(name, url,
  production_url)` dans `tests/db_safety.py`.
- Hors `local`, `Settings` **vide** `database_url_test` et
  `database_url_migrations_test` (jamais de crash pour un environnement qui les
  contient encore, comme la production actuelle).

- [ ] **Étape 1 : écrire les tests qui échouent**

```python
# backend/tests/test_config_guard.py
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
```

```python
# backend/tests/test_db_safety.py
import pytest

from tests.db_safety import assert_safe_test_database

PROD = "postgresql+asyncpg://u:p@host/control_center"


def test_accepts_dedicated_test_databases() -> None:
    assert_safe_test_database("X", "postgresql+asyncpg://u:p@h/control_center_test", PROD)
    assert_safe_test_database("X", "postgresql+asyncpg://u:p@h/cc_migrations?ssl=require", PROD)


@pytest.mark.parametrize(
    "url",
    [
        "",
        PROD,
        "postgresql+asyncpg://u:p@other/control_center",
        "postgresql+asyncpg://u:p@h/neondb",
        "postgresql+asyncpg://u:p@h/prod_test_backup_live",
    ],
)
def test_refuses_anything_that_is_not_a_disposable_database(url: str) -> None:
    with pytest.raises(RuntimeError):
        assert_safe_test_database("DATABASE_URL_TEST", url, PROD)
```

Lancer : `cd backend && .venv/Scripts/python.exe -m pytest tests/test_config_guard.py tests/test_db_safety.py -v`
Attendu : ÉCHEC (`ImportError: create_app`, `ModuleNotFoundError: tests.db_safety`).

- [ ] **Étape 2 : `tests/db_safety.py`**

```python
# backend/tests/db_safety.py
"""Garde-fou : la suite de tests détruit ses bases (`drop_all`, `downgrade base`).
Elle ne doit jamais pouvoir viser autre chose qu'une base jetable."""

from urllib.parse import urlsplit

_ALLOWED_SUFFIXES = ("_test", "_migrations")


def assert_safe_test_database(name: str, url: str, production_url: str) -> None:
    if not url:
        raise RuntimeError(
            f"{name} est vide : la suite de tests exige une base jetable dédiée "
            "(voir backend/.env.example)."
        )
    if url == production_url:
        raise RuntimeError(
            f"{name} est identique à DATABASE_URL : les tests détruiraient cette base."
        )
    database = urlsplit(url).path.rsplit("/", 1)[-1]
    if not database.endswith(_ALLOWED_SUFFIXES):
        raise RuntimeError(
            f"{name} vise la base « {database} » : seuls les noms finissant par "
            f"{' ou '.join(_ALLOWED_SUFFIXES)} sont autorisés pour les tests."
        )
```

Appeler la garde depuis les trois endroits qui détruisent une base :
- `backend/tests/conftest.py`, en tête de la fixture `engine` (avant `build_engine`) :

```python
from tests.db_safety import assert_safe_test_database
...
async def engine() -> AsyncGenerator:
    settings = get_settings()
    assert_safe_test_database(
        "DATABASE_URL_TEST", settings.database_url_test, settings.database_url
    )
    eng = build_engine(settings.database_url_test)
```
- `backend/tests/test_migrations.py`, juste après `MIG_URL = ...` :

```python
from tests.db_safety import assert_safe_test_database

assert_safe_test_database(
    "DATABASE_URL_MIGRATIONS_TEST", MIG_URL, get_settings().database_url
)
```
- `backend/tests/test_enum_check_constraints.py`, juste après `_MIG_URL = ...`, même appel avec `_MIG_URL`.

- [ ] **Étape 3 : `app/config.py`**

Remplacer les imports et le début de la classe, et ajouter le validateur à la fin de
`Settings` :

```python
from functools import lru_cache
from typing import Literal, Self

from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    environment: Literal["local", "staging", "production"] = "local"

    database_url: str
    # Bases jetables des tests. Vides et ignorées hors `local` : elles n'ont aucun
    # sens en déploiement, et une base de test qui pointerait sur la vraie base
    # serait détruite par `drop_all`.
    database_url_test: str = ""
    database_url_migrations_test: str = ""
    redis_url: str = ""
    # (le reste des champs est inchangé)
```
Ajouter, dans la section « Où renvoyer le navigateur… » ou juste avant
`token_enc_keys`, les champs :

```python
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
```
Ajouter à la fin de la classe (après `app_secret_key`) :

```python
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
```

- [ ] **Étape 4 : `create_app` dans `app/main.py`**

Réécrire le fichier ainsi (la journalisation et Sentry sont branchés aux tâches 2 et 3 ;
ne rien ajouter d'autre ici) :

```python
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.router import api_router
from app.config import Settings, get_settings
from app.db.session import engine, get_session

# Le logger racine n'a par défaut aucun handler (niveau WARNING) : sans ceci,
# tout logger.info() applicatif (ex. ConsoleEmailSender) est silencieusement
# avalé au runtime. Remplacé à la tâche 2 par `configure_logging`.
logging.basicConfig(
    level=logging.INFO, format="%(levelname)s %(name)s: %(message)s", force=True
)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    yield
    await engine.dispose()


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    docs = settings.api_docs_enabled
    application = FastAPI(
        title="Control Center Marketing Agentique",
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/docs" if docs else None,
        redoc_url="/redoc" if docs else None,
        openapi_url="/openapi.json" if docs else None,
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["Content-Disposition"],
    )
    application.include_router(api_router, prefix="/api/v1")

    @application.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @application.get("/health/db", response_model=None)
    async def health_db(
        session: Annotated[AsyncSession, Depends(get_session)],
    ) -> dict[str, str] | JSONResponse:
        try:
            await session.execute(text("SELECT 1"))
        except Exception:
            return JSONResponse(status_code=503, content={"database": "error"})
        return {"database": "ok"}

    return application


app = create_app()
```

- [ ] **Étape 5 : lancer**

```bash
cd backend
.venv/Scripts/python.exe -m pytest tests/test_config_guard.py tests/test_db_safety.py tests/test_config.py tests/test_health.py tests/test_db_health.py -v
.venv/Scripts/python.exe -m pytest -W error -q
uv run ruff check app tests
```
Attendu : tout vert. **Vérifier le cas de la production actuelle** sans rien
modifier en ligne : avec les variables réelles simulées (mêmes valeurs que le service :
`ENVIRONMENT=production`, mocks à `false`, `DATABASE_URL_TEST=DATABASE_URL`), la
construction de `Settings` réussit et vide les URL de test (couvert par
`test_valid_production_passes_and_ignores_test_databases`).

- [ ] **Étape 6 : commit**

```bash
git add backend/app/config.py backend/app/main.py backend/tests
git commit -m "feat(prod): configuration par environnement, garde de production et securite des bases de test"
```

---

### Tâche 2 : Journaux JSON, identifiant de requête et journal d'accès

**Fichiers :**
- Créer : `backend/app/logging_config.py`
- Modifier : `backend/app/main.py`
- Test : `backend/tests/test_logging_config.py`

**Interfaces :**
- Consomme : `Settings.json_logs` (Tâche 1), `create_app` (Tâche 1).
- Produit : `request_id_var: ContextVar[str | None]`, `JsonFormatter`,
  `configure_logging(settings)`, `RequestContextMiddleware` (ASGI pur). Le logger
  `app.access` émet une ligne par requête avec `method`, `path` (**gabarit de route**,
  jamais le chemin réel), `status`, `duration_ms`.
- Garanties de confidentialité : ni chaîne de requête, ni chemin brut (un chemin
  comme `/invitations/{token}` contient un secret), ni corps, ni en-têtes.

- [ ] **Étape 1 : écrire les tests qui échouent**

```python
# backend/tests/test_logging_config.py
import json
import logging

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.logging_config import (
    JsonFormatter,
    RequestContextMiddleware,
    configure_logging,
    request_id_var,
)


def _record(message: str = "bonjour", level: int = logging.INFO, **extra) -> logging.LogRecord:
    record = logging.LogRecord("app.test", level, __file__, 1, message, (), None)
    for key, value in extra.items():
        setattr(record, key, value)
    return record


def test_json_formatter_emits_cloud_logging_fields() -> None:
    line = JsonFormatter().format(_record("bonjour", logging.WARNING))
    payload = json.loads(line)
    assert payload["severity"] == "WARNING"
    assert payload["message"] == "bonjour"
    assert payload["logger"] == "app.test"
    assert "time" in payload


def test_json_formatter_adds_request_id_and_extra_fields() -> None:
    token = request_id_var.set("req-12345678")
    try:
        payload = json.loads(JsonFormatter().format(_record(status=201, path="/x")))
    finally:
        request_id_var.reset(token)
    assert payload["request_id"] == "req-12345678"
    assert payload["status"] == 201
    assert payload["path"] == "/x"


def test_json_formatter_includes_the_traceback_in_the_message() -> None:
    try:
        raise ValueError("boom")
    except ValueError:
        import sys

        record = _record("échec", logging.ERROR)
        record.exc_info = sys.exc_info()
    payload = json.loads(JsonFormatter().format(record))
    assert payload["severity"] == "ERROR"
    assert "Traceback" in payload["message"] and "ValueError: boom" in payload["message"]


def _app() -> FastAPI:
    application = FastAPI()
    application.add_middleware(RequestContextMiddleware)

    @application.get("/items/{item_id}")
    async def item(item_id: str) -> dict[str, str]:
        return {"id": item_id, "rid": request_id_var.get() or ""}

    @application.get("/boom")
    async def boom() -> None:
        raise RuntimeError("kaboom")

    @application.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return application


def _client(application: FastAPI) -> AsyncClient:
    transport = ASGITransport(app=application, raise_app_exceptions=False)
    return AsyncClient(transport=transport, base_url="http://t")


async def test_request_id_is_generated_and_returned(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger="app.access")
    async with _client(_app()) as client:
        response = await client.get("/items/abc")
    rid = response.headers["x-request-id"]
    assert len(rid) >= 8
    assert response.json()["rid"] == rid  # visible dans le contexte du handler


async def test_valid_incoming_request_id_is_kept_and_invalid_one_replaced() -> None:
    async with _client(_app()) as client:
        kept = await client.get("/items/a", headers={"X-Request-ID": "trace-abcdef123"})
        bad = await client.get("/items/a", headers={"X-Request-ID": "x y\tz"})
    assert kept.headers["x-request-id"] == "trace-abcdef123"
    assert bad.headers["x-request-id"] != "x y\tz"


async def test_cloud_trace_header_becomes_the_request_id() -> None:
    trace = "105445aa7843bc8bf206b12000100000"
    async with _client(_app()) as client:
        response = await client.get(
            "/items/a", headers={"X-Cloud-Trace-Context": f"{trace}/1;o=1"}
        )
    assert response.headers["x-request-id"] == trace


async def test_access_log_uses_the_route_template_and_never_the_query(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger="app.access")
    async with _client(_app()) as client:
        await client.get("/items/SECRET-TOKEN-VALUE?code=OAUTH-CODE&state=abc")
    records = [r for r in caplog.records if r.name == "app.access"]
    assert len(records) == 1
    record = records[0]
    assert record.path == "/items/{item_id}"
    assert record.status == 200 and record.method == "GET"
    assert record.duration_ms >= 0
    everything = " ".join(f"{r.getMessage()} {r.__dict__}" for r in caplog.records)
    assert "SECRET-TOKEN-VALUE" not in everything
    assert "OAUTH-CODE" not in everything


async def test_unmatched_routes_are_logged_without_the_raw_path(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger="app.access")
    async with _client(_app()) as client:
        response = await client.get("/secret/path/with-token-123")
    assert response.status_code == 404
    record = next(r for r in caplog.records if r.name == "app.access")
    assert record.path == "unmatched"
    assert "with-token-123" not in str(record.__dict__)


async def test_unhandled_exception_is_logged_as_error_with_the_request_id(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger="app.access")
    async with _client(_app()) as client:
        response = await client.get("/boom")
    assert response.status_code == 500
    errors = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert errors and errors[0].exc_info is not None
    assert any(r.__dict__.get("status") == 500 for r in caplog.records)


async def test_health_checks_are_logged_at_debug_only(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger="app.access")
    async with _client(_app()) as client:
        await client.get("/health")
    assert [r for r in caplog.records if r.name == "app.access"] == []


def test_configure_logging_is_idempotent_and_leaves_foreign_handlers() -> None:
    from app.config import Settings

    foreign = logging.NullHandler()
    root = logging.getLogger()
    root.addHandler(foreign)
    settings = Settings(
        _env_file=None,
        database_url="postgresql+asyncpg://u:p@h/db",
        token_enc_keys={1: "a" * 44},
        token_enc_active_version=1,
        app_secret_key="x" * 40,
    )
    try:
        configure_logging(settings)
        configure_logging(settings)
        managed = [h for h in root.handlers if getattr(h, "_cc_managed", False)]
        assert len(managed) == 1
        assert foreign in root.handlers
    finally:
        root.removeHandler(foreign)
        for handler in [h for h in root.handlers if getattr(h, "_cc_managed", False)]:
            root.removeHandler(handler)
```

Lancer → ÉCHEC (module absent).

- [ ] **Étape 2 : implémenter `app/logging_config.py`**

```python
# backend/app/logging_config.py
"""Journalisation structurée et contexte de requête.

Objectifs :
- une ligne JSON par événement en production (Cloud Logging la structure seule) ;
- un identifiant de requête (`request_id`) présent dans toutes les lignes émises
  pendant la requête ;
- une ligne d'accès par requête, **sans chaîne de requête ni chemin brut** (les
  codes OAuth, jetons d'invitation et de réinitialisation y figureraient).
Les exceptions non gérées sont journalisées en ERROR avec leur traceback dans le
message : Cloud Error Reporting les regroupe sans configuration supplémentaire.
"""

from __future__ import annotations

import json
import logging
import re
import sys
import time
import uuid
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.config import Settings

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)

_STANDARD_ATTRS = frozenset(
    logging.LogRecord("", 0, "", 0, "", (), None).__dict__
) | {"message", "asctime", "taskName"}

_ACCESS = logging.getLogger("app.access")
_ID_PATTERN = re.compile(r"^[A-Za-z0-9._\-]{8,64}$")
_TRACE_PATTERN = re.compile(r"^[0-9a-f]{32}$")
_QUIET_PATHS = frozenset({"/health", "/health/db"})


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        message = record.getMessage()
        if record.exc_info:
            message = f"{message}\n{self.formatException(record.exc_info)}"
        payload: dict[str, Any] = {
            "severity": record.levelname,
            "message": message,
            "logger": record.name,
            "time": datetime.fromtimestamp(record.created, UTC).isoformat(),
        }
        request_id = request_id_var.get()
        if request_id:
            payload["request_id"] = request_id
        for key, value in record.__dict__.items():
            if key not in _STANDARD_ATTRS and not key.startswith("_"):
                payload[key] = value
        return json.dumps(payload, default=str, ensure_ascii=False)


class _RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get() or "-"
        return True


def configure_logging(settings: Settings) -> None:
    """Installe le handler applicatif ; sans effet sur les handlers étrangers
    (pytest, uvicorn) et sans doublon si appelée plusieurs fois."""
    root = logging.getLogger()
    for handler in [h for h in root.handlers if getattr(h, "_cc_managed", False)]:
        root.removeHandler(handler)

    handler = logging.StreamHandler(sys.stdout)
    handler._cc_managed = True  # type: ignore[attr-defined]
    handler.addFilter(_RequestIdFilter())
    if settings.json_logs:
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(
            logging.Formatter("%(levelname)s [%(request_id)s] %(name)s: %(message)s")
        )
    root.addHandler(handler)
    root.setLevel(logging.INFO)
    # uvicorn journalise le chemin COMPLET, chaîne de requête comprise (codes OAuth) :
    # la ligne d'accès de `RequestContextMiddleware` la remplace.
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)


def _incoming_request_id(headers: list[tuple[bytes, bytes]]) -> str:
    trace: str | None = None
    for name, value in headers:
        text = value.decode("latin-1")
        if name == b"x-request-id" and _ID_PATTERN.match(text):
            return text
        if name == b"x-cloud-trace-context":
            candidate = text.split("/", 1)[0]
            if _TRACE_PATTERN.match(candidate):
                trace = candidate
    return trace or uuid.uuid4().hex


class RequestContextMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = _incoming_request_id(scope.get("headers", []))
        token = request_id_var.set(request_id)
        started = time.perf_counter()
        status_code = 500

        async def send_with_request_id(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
                headers = [*message.get("headers", []), (b"x-request-id", request_id.encode())]
                message = {**message, "headers": headers}
            await send(message)

        try:
            await self.app(scope, receive, send_with_request_id)
        except Exception:
            _ACCESS.exception("exception non gérée")
            raise
        finally:
            route = scope.get("route")
            path = getattr(route, "path", None) or "unmatched"
            level = logging.DEBUG if path in _QUIET_PATHS else logging.INFO
            _ACCESS.log(
                level,
                "request",
                extra={
                    "method": scope["method"],
                    "path": path,
                    "status": status_code,
                    "duration_ms": round((time.perf_counter() - started) * 1000, 1),
                },
            )
            request_id_var.reset(token)
```

- [ ] **Étape 3 : brancher dans `app/main.py`**

Remplacer le bloc `logging.basicConfig(...)` et son commentaire par l'import
`from app.logging_config import RequestContextMiddleware, configure_logging` et, dans
`create_app`, juste après `settings = settings or get_settings()` :

```python
    configure_logging(settings)
```
puis ajouter, **après** l'ajout du `CORSMiddleware` (donc plus externe) :

```python
    application.add_middleware(RequestContextMiddleware)
```
Supprimer `import logging` devenu inutile de `main.py`.

Les deux tests de `test_config_guard.py` qui appellent `create_app` avec une
configuration de production installent des logs JSON sur le logger racine. Pour ne pas
polluer les tests suivants, ajouter en haut de `test_config_guard.py` :

```python
from app.config import get_settings
from app.logging_config import configure_logging


@pytest.fixture(autouse=True)
def _restore_logging():
    yield
    configure_logging(get_settings())
```

- [ ] **Étape 4 : lancer**

```bash
cd backend
.venv/Scripts/python.exe -m pytest tests/test_logging_config.py tests/test_config_guard.py -v
.venv/Scripts/python.exe -m pytest -W error -q
uv run ruff check app tests
```
Vérifier aussi à la main, en démarrant l'API en local : une requête
`curl -i http://127.0.0.1:8020/api/v1/auth/me` renvoie l'en-tête `x-request-id` et une
ligne `INFO [<id>] app.access: request` dans la console, sans chemin brut.

- [ ] **Étape 5 : commit**

```bash
git add backend/app/logging_config.py backend/app/main.py backend/tests/test_logging_config.py
git commit -m "feat(prod): logs JSON, identifiant de requete et journal d'acces sans donnees sensibles"
```

---

### Tâche 3 : Suivi d'erreurs (Sentry), optionnel et épuré

**Fichiers :**
- Créer : `backend/app/observability.py`
- Modifier : `backend/app/main.py`, `backend/pyproject.toml`, `backend/uv.lock`
- Test : `backend/tests/test_observability.py`

**Interfaces :**
- Consomme : `Settings.sentry_dsn`, `Settings.sentry_traces_sample_rate`,
  `Settings.environment`.
- Produit : `scrub_event(event, hint) -> dict | None` (purge), `init_sentry(settings)
  -> bool` (`False` et aucun effet sans DSN).
- Sans `SENTRY_DSN`, rien n'est initialisé : aucun compte n'est requis.

- [ ] **Étape 1 : ajouter la dépendance**

```bash
cd backend
uv add "sentry-sdk[fastapi]>=2.20"
```
(le fichier `uv.lock` est mis à jour ; à committer avec la tâche).

- [ ] **Étape 2 : écrire les tests qui échouent**

```python
# backend/tests/test_observability.py
import pytest

from app.config import Settings
from app.observability import init_sentry, scrub_event


def _settings(**overrides: object) -> Settings:
    return Settings(
        _env_file=None,
        database_url="postgresql+asyncpg://u:p@h/db",
        token_enc_keys={1: "a" * 44},
        token_enc_active_version=1,
        app_secret_key="x" * 40,
        **overrides,
    )


def test_scrub_event_drops_request_payloads_and_secrets() -> None:
    event = {
        "request": {
            "url": "https://api.example.com/api/v1/auth/google/callback?code=abc&state=def",
            "query_string": "code=abc&state=def",
            "cookies": {"cc_session": "SESSION"},
            "headers": {"Authorization": "Bearer X", "Cookie": "cc_session=SESSION"},
            "data": {"password": "hunter2"},
        },
        "extra": {"refresh_token": "R", "access_token": "A", "status_code": 500, "code": "C"},
        "contexts": {"auth": {"api_key": "K", "note": "ok"}},
        "message": "ok",
    }
    cleaned = scrub_event(event, {})
    assert cleaned is not None
    request = cleaned["request"]
    assert "query_string" not in request and "cookies" not in request
    assert "headers" not in request and "data" not in request
    assert "code=abc" not in request["url"] and request["url"].endswith("/callback")
    assert cleaned["extra"]["refresh_token"] == "[Filtered]"
    assert cleaned["extra"]["access_token"] == "[Filtered]"
    assert cleaned["extra"]["code"] == "[Filtered]"
    assert cleaned["extra"]["status_code"] == 500  # « code » exact seulement
    assert cleaned["contexts"]["auth"]["api_key"] == "[Filtered]"
    assert cleaned["contexts"]["auth"]["note"] == "ok"
    assert cleaned["message"] == "ok"


def test_scrub_event_tolerates_events_without_request() -> None:
    assert scrub_event({"message": "x"}, {}) == {"message": "x"}


def test_init_is_a_no_op_without_dsn() -> None:
    assert init_sentry(_settings()) is False


def test_init_configures_a_private_client(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict = {}
    import sentry_sdk

    monkeypatch.setattr(sentry_sdk, "init", lambda **kwargs: captured.update(kwargs))
    monkeypatch.setenv("K_REVISION", "backend-guiili-00042-abc")
    settings = _settings(
        sentry_dsn="https://public@example.ingest.sentry.io/1",
        sentry_traces_sample_rate=0.1,
        environment="staging",
        frontend_base_url="https://app.example.com",
        cors_origins=["https://app.example.com"],
    )
    assert init_sentry(settings) is True
    assert captured["dsn"] == "https://public@example.ingest.sentry.io/1"
    assert captured["environment"] == "staging"
    assert captured["release"] == "backend-guiili-00042-abc"
    assert captured["send_default_pii"] is False
    assert captured["traces_sample_rate"] == 0.1
    assert captured["max_request_body_size"] == "never"
    assert captured["before_send"] is scrub_event
```

Lancer → ÉCHEC (module absent).

- [ ] **Étape 3 : implémenter `app/observability.py`**

```python
# backend/app/observability.py
"""Suivi d'erreurs Sentry, désactivé tant que SENTRY_DSN est vide.

Règle : Sentry ne reçoit jamais de contenu de requête. On coupe l'envoi du corps, des
cookies, des en-têtes et de la chaîne de requête à la source ET on nettoie chaque
événement (`scrub_event`) pour les données ajoutées ailleurs (extra, contextes).
"""

from __future__ import annotations

import os
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from app.config import Settings

_FILTERED = "[Filtered]"
# Noms courts : correspondance exacte (évite de masquer « status_code »).
_EXACT_KEYS = frozenset({"code", "state", "key"})
# Fragments : correspondance par sous-chaîne.
_SUBSTRING_KEYS = (
    "password",
    "secret",
    "token",
    "authorization",
    "cookie",
    "api_key",
    "apikey",
    "refresh",
)
_DROPPED_REQUEST_KEYS = ("query_string", "cookies", "headers", "data")


def _is_sensitive(key: str) -> bool:
    lowered = key.lower()
    return lowered in _EXACT_KEYS or any(part in lowered for part in _SUBSTRING_KEYS)


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _FILTERED if isinstance(key, str) and _is_sensitive(key) else _redact(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact(item) for item in value]
    return value


def scrub_event(event: dict[str, Any], hint: dict[str, Any]) -> dict[str, Any] | None:
    request = event.get("request")
    if isinstance(request, dict):
        for key in _DROPPED_REQUEST_KEYS:
            request.pop(key, None)
        url = request.get("url")
        if isinstance(url, str):
            parts = urlsplit(url)
            request["url"] = urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))
    for section in ("extra", "contexts", "tags", "breadcrumbs"):
        if section in event:
            event[section] = _redact(event[section])
    return event


def init_sentry(settings: Settings) -> bool:
    dsn = settings.sentry_dsn.get_secret_value()
    if not dsn:
        return False
    import sentry_sdk

    sentry_sdk.init(
        dsn=dsn,
        environment=settings.environment,
        release=os.environ.get("K_REVISION") or None,
        send_default_pii=False,
        traces_sample_rate=settings.sentry_traces_sample_rate,
        max_request_body_size="never",
        before_send=scrub_event,
    )
    return True
```

- [ ] **Étape 4 : brancher dans `create_app`**

Dans `app/main.py` : `from app.observability import init_sentry` et, dans `create_app`,
juste après `configure_logging(settings)` : `init_sentry(settings)`.

- [ ] **Étape 5 : lancer**

```bash
cd backend
.venv/Scripts/python.exe -m pytest tests/test_observability.py -v
.venv/Scripts/python.exe -m pytest -W error -q
uv run ruff check app tests
```
Attendu : vert (aucune initialisation réelle de Sentry pendant les tests).

- [ ] **Étape 6 : commit**

```bash
git add backend/app/observability.py backend/app/main.py backend/tests/test_observability.py backend/pyproject.toml backend/uv.lock
git commit -m "feat(prod): suivi d'erreurs Sentry optionnel avec purge des donnees sensibles"
```

---

### Tâche 4 : Limitation de débit des routes sensibles

**Fichiers :**
- Créer : `backend/app/security/rate_limit.py`, `backend/app/api/rate_limit.py`
- Modifier : `backend/app/api/v1/endpoints/{auth,connections,websites,audit,advisor}.py`,
  `backend/tests/conftest.py`
- Test : `backend/tests/test_rate_limit.py`, `backend/tests/test_rate_limit_endpoints.py`

**Interfaces :**
- Produit : `SlidingWindowLimiter` (`retry_after`, `record`, `check`, `reset`),
  instance globale `limiter` ; `enforce(key, *, limit, window, enabled=True)` et
  `enforce_not_blocked(...)` (lèvent `HTTPException` 429 avec `Retry-After`) ;
  `client_ip(request)` ; dépendances `limit_by_ip(name, *, limit, window)` et
  `limit_by_user(name, *, limit, window)` (retournent un `Depends`).
- Limite **par instance** (mémoire du processus, jusqu'à 3 instances en production) :
  elle freine les abus et la force brute sans dépendre d'un service partagé. Une limite
  globale exacte viendra avec Redis ou le pare-feu, si le besoin se confirme.
- Sur `/auth/login`, seuls les **échecs** comptent pour la clé « e-mail » (un tiers ne
  peut pas verrouiller un compte en envoyant de bonnes requêtes, ni en réussissant).
  Attention : un tiers peut encore ralentir la connexion d'un utilisateur en envoyant
  de mauvais mots de passe ; c'est le compromis assumé (10 échecs par 15 minutes).

- [ ] **Étape 1 : écrire les tests du limiteur (qui échouent)**

```python
# backend/tests/test_rate_limit.py
import pytest
from fastapi import HTTPException

from app.security.rate_limit import SlidingWindowLimiter, client_ip, enforce


class _Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def test_allows_up_to_the_limit_then_blocks_with_retry_after() -> None:
    clock = _Clock()
    limiter = SlidingWindowLimiter(clock=clock)
    for _ in range(3):
        assert limiter.check("k", limit=3, window=60) == 0.0
        clock.now += 1
    retry = limiter.check("k", limit=3, window=60)
    assert 56 <= retry <= 58  # première requête à t=1000, fenêtre 60 s, now=1003


def test_window_expiry_frees_the_key() -> None:
    clock = _Clock()
    limiter = SlidingWindowLimiter(clock=clock)
    limiter.check("k", limit=1, window=10)
    assert limiter.check("k", limit=1, window=10) > 0
    clock.now += 11
    assert limiter.check("k", limit=1, window=10) == 0.0


def test_keys_are_independent_and_peek_does_not_record() -> None:
    limiter = SlidingWindowLimiter(clock=_Clock())
    limiter.check("a", limit=1, window=60)
    assert limiter.check("b", limit=1, window=60) == 0.0
    for _ in range(5):
        assert limiter.retry_after("c", limit=1, window=60) == 0.0
    limiter.record("c")
    assert limiter.retry_after("c", limit=1, window=60) > 0


def test_reset_clears_everything() -> None:
    limiter = SlidingWindowLimiter(clock=_Clock())
    limiter.check("k", limit=1, window=60)
    limiter.reset()
    assert limiter.check("k", limit=1, window=60) == 0.0


def test_expired_keys_are_collected_when_the_table_is_full() -> None:
    clock = _Clock()
    limiter = SlidingWindowLimiter(clock=clock, max_keys=100)
    for i in range(90):
        limiter.check(f"old{i}", limit=5, window=60)
    clock.now += 120  # toutes les clés précédentes ont expiré
    for i in range(20):
        limiter.check(f"new{i}", limit=5, window=60)
    # Le ramasse-miettes s'est déclenché au 101e passage : seules les récentes restent.
    assert len(limiter._hits) <= 21
    assert "old0" not in limiter._hits


def test_saturation_by_distinct_keys_never_grows_without_bound() -> None:
    limiter = SlidingWindowLimiter(clock=_Clock(), max_keys=100)
    for i in range(500):
        limiter.check(f"attack{i}", limit=5, window=60)
    assert len(limiter._hits) <= 101


def test_enforce_raises_429_with_retry_after_header() -> None:
    limiter_key = "test-enforce-429"
    enforce(limiter_key, limit=1, window=60)
    with pytest.raises(HTTPException) as excinfo:
        enforce(limiter_key, limit=1, window=60)
    assert excinfo.value.status_code == 429
    assert int(excinfo.value.headers["Retry-After"]) >= 1


def test_enforce_can_be_disabled() -> None:
    for _ in range(5):
        enforce("test-disabled", limit=1, window=60, enabled=False)


def test_client_ip_prefers_the_first_forwarded_address() -> None:
    class _Req:
        def __init__(self, headers: dict, host: str | None) -> None:
            self.headers = headers
            self.client = type("C", (), {"host": host})() if host else None

    assert client_ip(_Req({"x-forwarded-for": "203.0.113.5, 10.0.0.1"}, "10.0.0.1")) == "203.0.113.5"
    assert client_ip(_Req({}, "192.0.2.7")) == "192.0.2.7"
    assert client_ip(_Req({}, None)) == "unknown"
```

- [ ] **Étape 2 : `app/security/rate_limit.py`**

```python
# backend/app/security/rate_limit.py
"""Limiteur à fenêtre glissante, en mémoire, par instance.

Choix assumé : pas de dépendance externe. Avec plusieurs instances Cloud Run la limite
effective est multipliée par leur nombre ; elle suffit contre la force brute et les
boucles clientes. `X-Forwarded-For` est pris tel quel (meilleur effort : derrière le
proxy Vercel, le premier maillon est l'IP annoncée du client et peut être forgé) ; la
clé « e-mail » sur les routes d'authentification est le frein fiable.
"""

from __future__ import annotations

import math
import time
from collections import deque
from collections.abc import Callable
from typing import Protocol

from fastapi import HTTPException, status


class _RequestLike(Protocol):
    headers: dict[str, str]
    client: object | None


class SlidingWindowLimiter:
    def __init__(
        self, *, clock: Callable[[], float] = time.monotonic, max_keys: int = 50_000
    ) -> None:
        self._clock = clock
        self._max_keys = max_keys
        self._max_window = 0.0
        self._hits: dict[str, deque[float]] = {}

    def _prune(self, hits: deque[float], now: float, window: float) -> None:
        cutoff = now - window
        while hits and hits[0] <= cutoff:
            hits.popleft()

    def retry_after(self, key: str, *, limit: int, window: float) -> float:
        """Secondes avant qu'une requête soit permise (0.0 si permise), sans rien noter."""
        hits = self._hits.get(key)
        if not hits:
            return 0.0
        now = self._clock()
        self._prune(hits, now, window)
        if len(hits) < limit:
            return 0.0
        return max(hits[0] + window - now, 0.001)

    def record(self, key: str) -> None:
        self._hits.setdefault(key, deque()).append(self._clock())
        self._collect_garbage()

    def check(self, key: str, *, limit: int, window: float) -> float:
        """Note la requête si elle est permise ; sinon renvoie le délai d'attente."""
        self._max_window = max(self._max_window, window)
        wait = self.retry_after(key, limit=limit, window=window)
        if wait == 0.0:
            self.record(key)
        return wait

    def _collect_garbage(self) -> None:
        if len(self._hits) <= self._max_keys:
            return
        cutoff = self._clock() - self._max_window
        for key in [k for k, hits in self._hits.items() if not hits or hits[-1] <= cutoff]:
            del self._hits[key]
        if len(self._hits) > self._max_keys:
            # Saturation (attaque par clés distinctes) : on repart de zéro plutôt que de
            # croître sans borne ; la limite se rétablit aussitôt.
            self._hits.clear()

    def reset(self) -> None:
        self._hits.clear()


limiter = SlidingWindowLimiter()


def _too_many(wait: float) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail="trop de tentatives, réessaie dans quelques instants",
        headers={"Retry-After": str(max(1, math.ceil(wait)))},
    )


def enforce(key: str, *, limit: int, window: float, enabled: bool = True) -> None:
    """Note et contrôle : lève 429 si la limite est atteinte."""
    if not enabled:
        return
    wait = limiter.check(key, limit=limit, window=window)
    if wait > 0:
        raise _too_many(wait)


def enforce_not_blocked(key: str, *, limit: int, window: float, enabled: bool = True) -> None:
    """Contrôle sans noter (l'appelant note lui-même les seuls échecs)."""
    if not enabled:
        return
    wait = limiter.retry_after(key, limit=limit, window=window)
    if wait > 0:
        raise _too_many(wait)


def client_ip(request: _RequestLike) -> str:
    forwarded = request.headers.get("x-forwarded-for", "")
    first = forwarded.split(",")[0].strip()
    if first:
        return first
    host = getattr(request.client, "host", None)
    return host or "unknown"
```

Le test `test_memory_stays_bounded` suppose `max_window` mémorisé par `check` : c'est le
cas ci-dessus.

- [ ] **Étape 3 : dépendances FastAPI `app/api/rate_limit.py`**

```python
# backend/app/api/rate_limit.py
from __future__ import annotations

from fastapi import Depends, Request

from app.api.deps import CurrentUserDep, SettingsDep
from app.security.rate_limit import client_ip, enforce


def limit_by_ip(name: str, *, limit: int, window: float):
    async def _dependency(request: Request, settings: SettingsDep) -> None:
        enforce(
            f"{name}:ip:{client_ip(request)}",
            limit=limit,
            window=window,
            enabled=settings.rate_limit_enabled,
        )

    return Depends(_dependency)


def limit_by_user(name: str, *, limit: int, window: float):
    async def _dependency(user: CurrentUserDep, settings: SettingsDep) -> None:
        enforce(
            f"{name}:user:{user.id}",
            limit=limit,
            window=window,
            enabled=settings.rate_limit_enabled,
        )

    return Depends(_dependency)
```

- [ ] **Étape 4 : remise à zéro entre les tests**

Dans `backend/tests/conftest.py`, ajouter :

```python
from app.security.rate_limit import limiter


@pytest_asyncio.fixture(autouse=True)
async def _reset_rate_limiter() -> AsyncGenerator[None, None]:
    limiter.reset()
    yield
    limiter.reset()
```

- [ ] **Étape 5 : écrire les tests d'endpoints (qui échouent)**

```python
# backend/tests/test_rate_limit_endpoints.py
from httpx import AsyncClient

from app.config import get_settings
from app.models.user import User


async def _register(client: AsyncClient, email: str) -> int:
    resp = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "Motdepasse-solide-1", "display_name": "T"},
    )
    return resp.status_code


async def test_login_blocks_after_ten_failures_per_email(db_client: AsyncClient) -> None:
    await _register(db_client, "victime@example.com")
    db_client.cookies.clear()
    for _ in range(10):
        resp = await db_client.post(
            "/api/v1/auth/login", json={"email": "victime@example.com", "password": "mauvais"}
        )
        assert resp.status_code == 400
    blocked = await db_client.post(
        "/api/v1/auth/login", json={"email": "victime@example.com", "password": "mauvais"}
    )
    assert blocked.status_code == 429
    assert int(blocked.headers["retry-after"]) >= 1
    # Même le bon mot de passe est refusé pendant le blocage (force brute).
    good = await db_client.post(
        "/api/v1/auth/login",
        json={"email": "victime@example.com", "password": "Motdepasse-solide-1"},
    )
    assert good.status_code == 429
    # Une autre adresse n'est pas touchée.
    other = await db_client.post(
        "/api/v1/auth/login", json={"email": "autre@example.com", "password": "x"}
    )
    assert other.status_code == 400


async def test_successful_logins_do_not_consume_the_failure_budget(
    db_client: AsyncClient,
) -> None:
    await _register(db_client, "ok@example.com")
    for _ in range(12):
        resp = await db_client.post(
            "/api/v1/auth/login",
            json={"email": "ok@example.com", "password": "Motdepasse-solide-1"},
        )
        assert resp.status_code == 200


async def test_register_is_limited_per_ip(db_client: AsyncClient) -> None:
    statuses = [await _register(db_client, f"u{i}@example.com") for i in range(11)]
    assert statuses[:10] == [201] * 10
    assert statuses[10] == 429


async def test_password_reset_request_is_limited_per_email_without_leaking(
    db_client: AsyncClient,
) -> None:
    codes = []
    for _ in range(6):
        resp = await db_client.post(
            "/api/v1/auth/password-reset/request", json={"email": "inconnu@example.com"}
        )
        codes.append(resp.status_code)
    assert codes == [200] * 5 + [429]  # même comportement pour un e-mail inexistant


async def test_user_limited_route_returns_429_after_the_quota(
    authed_client: tuple[AsyncClient, User],
) -> None:
    client, _ = authed_client
    fake = "00000000-0000-0000-0000-000000000000"
    codes = [
        (await client.post(f"/api/v1/websites/{fake}/gtm/headless")).status_code
        for _ in range(4)
    ]
    assert codes == [404, 404, 404, 429]


async def test_limits_can_be_disabled_by_setting(
    db_client: AsyncClient, monkeypatch
) -> None:
    monkeypatch.setattr(get_settings(), "rate_limit_enabled", False)
    statuses = [await _register(db_client, f"d{i}@example.com") for i in range(12)]
    assert 429 not in statuses
```

Lancer → ÉCHEC.

- [ ] **Étape 6 : appliquer les limites**

Dans `backend/app/api/v1/endpoints/auth.py`, ajouter aux imports :

```python
from app.api.rate_limit import limit_by_ip
from app.security.rate_limit import enforce, enforce_not_blocked, limiter
```
Modifier les décorateurs et corps ci-dessous (le reste du fichier ne change pas) :

```python
@router.get("/start", response_model=StartResponse, dependencies=[limit_by_ip("google_start", limit=30, window=600)])
```
(et pour `/callback` : `dependencies=[limit_by_ip("google_callback", limit=60, window=600)]`),

```python
@auth_router.post(
    "/register",
    status_code=status.HTTP_201_CREATED,
    dependencies=[limit_by_ip("register", limit=10, window=3600)],
)
async def register(...)   # corps inchangé


_LOGIN_FAILURES = {"limit": 10, "window": 900}


@auth_router.post(
    "/login", dependencies=[limit_by_ip("login", limit=30, window=900)]
)
async def login(
    body: LoginRequest, response: Response, session: SessionDep, settings: SettingsDep
) -> None:
    email_key = f"login_failures:email:{body.email.lower()}"
    enforce_not_blocked(email_key, enabled=settings.rate_limit_enabled, **_LOGIN_FAILURES)
    user = (
        await session.execute(select(User).where(User.email == body.email))
    ).scalar_one_or_none()
    if user is None or user.password_hash is None:
        limiter.record(email_key)
        detail = (
            "ce compte utilise Google, pas de mot de passe"
            if user is not None
            else "email ou mot de passe incorrect"
        )
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)
    if not verify_password(body.password, user.password_hash):
        limiter.record(email_key)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="email ou mot de passe incorrect"
        )
    _set_session_cookie(response, user.id, settings)
```
```python
@auth_router.post(
    "/password-reset/request",
    dependencies=[limit_by_ip("password_reset", limit=20, window=3600)],
)
async def password_reset_request(
    body: PasswordResetRequest, session: SessionDep, settings: SettingsDep, email_sender: EmailSenderDep
) -> dict[str, str]:
    enforce(
        f"password_reset:email:{body.email.lower()}",
        limit=5,
        window=3600,
        enabled=settings.rate_limit_enabled,
    )
    ...  # reste inchangé
```
Dans `connections.py`, sur la route `GET /google/start` : ajouter
`dependencies=[limit_by_ip("connections_start", limit=30, window=600)]` (importer
`limit_by_ip`). Dans `websites.py`, sur `POST ""` (création de site) :
`dependencies=[limit_by_user("website_create", limit=20, window=3600)]`. Dans
`audit.py` : `POST /websites/{website_id}/scan` →
`limit_by_user("scan", limit=10, window=60)` ; `POST /websites/{website_id}/gtm/headless`
→ `limit_by_user("headless", limit=3, window=600)`. Dans `advisor.py` :
`POST /websites/{website_id}/advisor/brief` → `limit_by_user("advisor_brief", limit=5,
window=60)` ; `POST /advisor/threads/{thread_id}/messages` →
`limit_by_user("advisor_message", limit=20, window=60)`. Importer `limit_by_user` depuis
`app.api.rate_limit` dans chaque fichier concerné.

- [ ] **Étape 7 : lancer**

```bash
cd backend
.venv/Scripts/python.exe -m pytest tests/test_rate_limit.py tests/test_rate_limit_endpoints.py -v
.venv/Scripts/python.exe -m pytest -W error -q
uv run ruff check app tests
```
Attendu : tout vert. Si un test existant échoue à cause d'une limite (trop d'appels du
même utilisateur dans un test), **ne pas relever la limite** : le limiteur est remis à
zéro entre chaque test ; enquêter sur la cause réelle.

- [ ] **Étape 8 : commit**

```bash
git add backend/app backend/tests
git commit -m "feat(prod): limitation de debit des routes sensibles (auth, scan, headless, conseiller)"
```

---

### Tâche 5 : Suite d'isolation entre clients

**Fichiers :**
- Test : `backend/tests/test_tenant_isolation.py`
- Modifier (seulement si un test révèle une faille) : l'endpoint fautif.

**Interfaces :**
- Consomme : `authed_client` (l'attaquant), `make_user`, `db_session`, `app.openapi()`.
- Produit : un test d'**inventaire** qui échoue dès qu'une route portant un
  identifiant d'objet (`website_id`, `workspace_id`, `thread_id`, `issue_id`,
  `connection_id`) n'est pas déclarée dans `CASES`. Toute route future doit donc être
  ajoutée avec son cas d'isolation.
- **Règle :** si un cas d'isolation échoue (statut autre que 403 ou 404, fuite de
  donnée, donnée modifiée), c'est une **vraie faille** : écrire le test tel quel, le voir
  échouer, corriger l'endpoint, le voir passer. Ne jamais relâcher le test.

- [ ] **Étape 1 : écrire la suite**

```python
# backend/tests/test_tenant_isolation.py
"""Un utilisateur authentifié d'un workspace ne peut ni lire, ni modifier, ni supprimer
les objets d'un autre workspace, sur AUCUNE route portant un identifiant d'objet."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.main import app
from app.models.advisor import AdvisorThread
from app.models.enums import ConnectionStatus, IssueCategory, IssueSeverity, IssueStatus
from app.models.google_connection import GoogleConnection
from app.models.issue_item import IssueItem
from app.models.user import User
from app.models.website import Website
from app.models.website_google_link import WebsiteGoogleLink
from app.models.workspace_invitation import WorkspaceInvitation
from app.models.workspace_member import WorkspaceMember
from app.security.token_crypto import load_token_cipher
from app.services.connections import upsert_google_connection
from app.services.google_oauth.base import GoogleTokenResponse, GoogleUserInfo
from tests.conftest import owner_workspace_id

TENANT_PARAMS = ("{website_id}", "{workspace_id}", "{thread_id}", "{issue_id}", "{connection_id}")
VICTIM_DOMAIN = "victime-secrete.test"


@dataclass
class World:
    victim_user_id: UUID
    victim_workspace_id: UUID
    victim_website_id: UUID
    victim_issue_id: UUID
    victim_thread_id: UUID
    victim_connection_id: UUID
    attacker_workspace_id: UUID
    attacker_website_id: UUID
    attacker_connection_id: UUID

    def path_ids(self) -> dict[str, str]:
        return {
            "website_id": str(self.victim_website_id),
            "workspace_id": str(self.victim_workspace_id),
            "thread_id": str(self.victim_thread_id),
            "issue_id": str(self.victim_issue_id),
            "connection_id": str(self.victim_connection_id),
            "member_user_id": str(self.victim_user_id),
        }


Body = dict | Callable[[World], dict] | None

# (méthode, gabarit de route sans /api/v1) -> corps de requête valide, ou None.
CASES: dict[tuple[str, str], Body] = {
    ("GET", "/websites/{website_id}/overview"): None,
    ("GET", "/websites/{website_id}/audit"): None,
    ("GET", "/websites/{website_id}/issues"): None,
    ("GET", "/websites/{website_id}/snippets"): None,
    ("GET", "/websites/{website_id}/ssl"): None,
    ("GET", "/websites/{website_id}/stack-hint"): None,
    ("GET", "/websites/{website_id}/google-links"): None,
    ("GET", "/websites/{website_id}/gtm-export"): None,
    ("GET", "/websites/{website_id}/advisor/threads"): None,
    ("POST", "/websites/{website_id}/scan"): None,
    ("POST", "/websites/{website_id}/gtm/headless"): None,
    ("POST", "/websites/{website_id}/advisor/brief"): None,
    ("POST", "/websites/{website_id}/redetect"): {},
    ("POST", "/websites/{website_id}/link-resource"): lambda w: {
        "google_connection_id": str(w.attacker_connection_id),
        "resource_type": "ga4_property",
        "resource_id": "properties/1",
    },
    ("PATCH", "/websites/{website_id}/stack"): {"stack_label": "Piraté"},
    ("PATCH", "/websites/{website_id}/issues/{issue_id}"): {"status": "dismissed"},
    ("DELETE", "/websites/{website_id}"): None,
    ("GET", "/advisor/threads/{thread_id}"): None,
    ("DELETE", "/advisor/threads/{thread_id}"): None,
    ("POST", "/advisor/threads/{thread_id}/messages"): {"text": "bonjour"},
    ("DELETE", "/connections/{connection_id}"): None,
    ("POST", "/workspaces/{workspace_id}/invitations"): {"invited_email": "intrus@example.com"},
    ("DELETE", "/workspaces/{workspace_id}/members/{member_user_id}"): None,
}

# Routes portant un identifiant mais volontairement hors de cette suite, avec la raison.
ALLOWLIST: dict[tuple[str, str], str] = {}


async def _connection(
    session: AsyncSession, workspace_id: UUID, sub: str, email: str
) -> GoogleConnection:
    return await upsert_google_connection(
        session,
        workspace_id=workspace_id,
        userinfo=GoogleUserInfo(sub=sub, email=email),
        token=GoogleTokenResponse(
            access_token="access",
            expires_in=3600,
            scopes=("openid",),
            refresh_token=f"refresh-{sub}",
        ),
        cipher=load_token_cipher(get_settings()),
    )


@pytest_asyncio.fixture
async def world(
    authed_client: tuple[AsyncClient, User], db_session: AsyncSession, make_user
) -> World:
    _, attacker = authed_client
    attacker_workspace = await owner_workspace_id(db_session, attacker)
    victim = await make_user(sub="victim-sub", email="victim@example.com", name="Victime")
    victim_workspace = await owner_workspace_id(db_session, victim)

    victim_site = Website(
        workspace_id=victim_workspace, domain=VICTIM_DOMAIN, display_name="Victime"
    )
    attacker_site = Website(
        workspace_id=attacker_workspace, domain="attaquant.test", display_name="Attaquant"
    )
    db_session.add_all([victim_site, attacker_site])
    await db_session.flush()

    issue = IssueItem(
        website_id=victim_site.id,
        title="Titre confidentiel",
        description="Description confidentielle",
        category=IssueCategory.SEO,
        severity=IssueSeverity.LOW,
        status=IssueStatus.TODO,
        fingerprint="fp-victim",
        detected_at=datetime.now(UTC),
    )
    thread = AdvisorThread(
        website_id=victim_site.id, persona_key="default", title="Fil confidentiel"
    )
    db_session.add_all([issue, thread])
    victim_connection = await _connection(
        db_session, victim_workspace, "victim-google", "victime.g@gmail.com"
    )
    attacker_connection = await _connection(
        db_session, attacker_workspace, "attacker-google", "attaquant.g@gmail.com"
    )
    await db_session.flush()

    return World(
        victim_user_id=victim.id,
        victim_workspace_id=victim_workspace,
        victim_website_id=victim_site.id,
        victim_issue_id=issue.id,
        victim_thread_id=thread.id,
        victim_connection_id=victim_connection.id,
        attacker_workspace_id=attacker_workspace,
        attacker_website_id=attacker_site.id,
        attacker_connection_id=attacker_connection.id,
    )


def _exposed_tenant_routes() -> set[tuple[str, str]]:
    exposed: set[tuple[str, str]] = set()
    for path, operations in app.openapi()["paths"].items():
        if any(param in path for param in TENANT_PARAMS):
            for method in operations:
                exposed.add((method.upper(), path.removeprefix("/api/v1")))
    return exposed


def test_every_tenant_route_has_an_isolation_case() -> None:
    exposed = _exposed_tenant_routes()
    missing = exposed - set(CASES) - set(ALLOWLIST)
    stale = set(CASES) - exposed
    assert not missing, (
        "Routes avec identifiant d'objet sans cas d'isolation : "
        f"{sorted(missing)}. Ajouter chacune à CASES (ou à ALLOWLIST avec la raison)."
    )
    assert not stale, f"CASES référence des routes qui n'existent plus : {sorted(stale)}"


async def test_anonymous_requests_are_rejected_everywhere(db_client: AsyncClient) -> None:
    fake = World(*(uuid4() for _ in range(9)))  # identifiants aléatoires, aucune base
    wrong: list[str] = []
    for (method, template), body in CASES.items():
        payload = body(fake) if callable(body) else body
        resp = await db_client.request(
            method, "/api/v1" + template.format_map(fake.path_ids()), json=payload
        )
        if resp.status_code != 401:
            wrong.append(f"{method} {template} -> {resp.status_code}")
    assert not wrong, wrong


async def test_a_stranger_cannot_reach_or_alter_another_workspace(
    authed_client: tuple[AsyncClient, User], db_session: AsyncSession, world: World
) -> None:
    client, _ = authed_client
    failures: list[str] = []
    for (method, template), body in CASES.items():
        payload = body(world) if callable(body) else body
        path = "/api/v1" + template.format_map(world.path_ids())
        resp = await client.request(method, path, json=payload)
        if resp.status_code not in (403, 404):
            failures.append(f"{method} {template} -> {resp.status_code}")
        if VICTIM_DOMAIN in resp.text or "confidentiel" in resp.text.lower():
            failures.append(f"{method} {template} : la réponse contient des données de la victime")
    assert not failures, "\n".join(failures)

    # Rien n'a bougé chez la victime.
    db_session.expire_all()
    site = await db_session.get(Website, world.victim_website_id)
    assert site is not None and site.stack_label is None and site.archived_at is None
    issue = await db_session.get(IssueItem, world.victim_issue_id)
    assert issue is not None and issue.status == IssueStatus.TODO
    thread = await db_session.get(AdvisorThread, world.victim_thread_id)
    assert thread is not None and thread.archived_at is None
    connection = await db_session.get(GoogleConnection, world.victim_connection_id)
    assert connection is not None and connection.status == ConnectionStatus.ACTIVE
    invitations = await db_session.scalar(
        select(func.count())
        .select_from(WorkspaceInvitation)
        .where(WorkspaceInvitation.workspace_id == world.victim_workspace_id)
    )
    members = await db_session.scalar(
        select(func.count())
        .select_from(WorkspaceMember)
        .where(WorkspaceMember.workspace_id == world.victim_workspace_id)
    )
    links = await db_session.scalar(select(func.count()).select_from(WebsiteGoogleLink))
    assert invitations == 0 and members == 1 and links == 0


async def test_cannot_patch_a_victim_issue_through_an_own_website(
    authed_client: tuple[AsyncClient, User], world: World, db_session: AsyncSession
) -> None:
    client, _ = authed_client
    resp = await client.patch(
        f"/api/v1/websites/{world.attacker_website_id}/issues/{world.victim_issue_id}",
        json={"status": "dismissed"},
    )
    assert resp.status_code == 404
    db_session.expire_all()
    issue = await db_session.get(IssueItem, world.victim_issue_id)
    assert issue is not None and issue.status == IssueStatus.TODO


async def test_cannot_link_a_victim_connection_to_an_own_website(
    authed_client: tuple[AsyncClient, User], world: World, db_session: AsyncSession
) -> None:
    client, _ = authed_client
    resp = await client.post(
        f"/api/v1/websites/{world.attacker_website_id}/link-resource",
        json={
            "google_connection_id": str(world.victim_connection_id),
            "resource_type": "ga4_property",
            "resource_id": "properties/1",
        },
    )
    # L'endpoint répond 400 « connexion Google invalide pour cet utilisateur » :
    # refus explicite, ce qui compte est qu'aucune liaison ne soit créée.
    assert resp.status_code in (400, 403, 404)
    assert await db_session.scalar(select(func.count()).select_from(WebsiteGoogleLink)) == 0


async def test_website_list_never_contains_another_workspace(
    authed_client: tuple[AsyncClient, User], world: World
) -> None:
    client, _ = authed_client
    resp = await client.get("/api/v1/websites")
    assert resp.status_code == 200
    domains = {site["domain"] for site in resp.json()}
    assert "attaquant.test" in domains
    assert VICTIM_DOMAIN not in domains
```

- [ ] **Étape 2 : lancer**

`cd backend && .venv/Scripts/python.exe -m pytest tests/test_tenant_isolation.py -v`

Trois issues possibles :
1. Tout est vert : bon, l'isolation est déjà correcte ; passer à l'étape 4.
2. `test_every_tenant_route_has_an_isolation_case` échoue : une route manque ou le nom
   d'un paramètre diffère. Compléter `CASES` avec le gabarit exact affiché par le
   message.
3. Un cas échoue avec un statut inattendu (par exemple 422 parce que le corps du cas est
   invalide) : lire le schéma de la requête de la route dans son fichier d'endpoint et
   corriger le **corps du cas** (jamais l'attente `403/404`). Si le statut est 200/201/
   204 ou si une donnée fuit : c'est une faille, voir étape 3.

- [ ] **Étape 3 : corriger toute faille découverte**

Pour chaque faille : l'endpoint doit appeler `owned_website(...)` ou `require_owner(...)`
(`backend/app/services/workspaces.py`) **avant** toute lecture ou écriture, et toute
ressource identifiée par son propre identifiant (issue, thread, connexion) doit être
rattachée au workspace de l'utilisateur. Écrire la correction minimale, relancer la suite
complète, puis noter la faille et sa correction dans le compte rendu de la tâche.

- [ ] **Étape 4 : lancer**

```bash
cd backend
.venv/Scripts/python.exe -m pytest tests/test_tenant_isolation.py -v
.venv/Scripts/python.exe -m pytest -W error -q
uv run ruff check app tests
```

- [ ] **Étape 5 : commit**

```bash
git add backend/tests/test_tenant_isolation.py backend/app
git commit -m "test(prod): suite d'isolation entre clients avec inventaire des routes"
```

---

### Tâche 6 : Migrations hors démarrage et déploiement scripté

**Fichiers :**
- Modifier : `backend/Dockerfile`, `.gitignore`, `backend/pyproject.toml`, `backend/uv.lock`
- Créer : `backend/app/tools/__init__.py`, `backend/app/tools/check_env.py`,
  `scripts/deploy-backend.sh`, `scripts/export-service-env.sh`,
  `deploy/env.example.yaml`
- Test : `backend/tests/test_deploy_assets.py`

**Interfaces :**
- Consomme : `Settings` et sa validation (Tâche 1).
- Produit : `validate_env(mapping) -> list[str]` (liste de problèmes, vide si valide) et
  `python -m app.tools.check_env FICHIER.yaml` ; `scripts/deploy-backend.sh
  <staging|production> [--dry-run]` ; `scripts/export-service-env.sh <staging|production>`.
- Déroulé du déploiement : vérifier le fichier d'environnement, construire l'image,
  **exécuter les migrations dans un Cloud Run Job et attendre son succès**, puis
  déployer le service, puis vérifier `/health/db`. Un échec de migration arrête tout :
  le service n'est pas touché.
- `--env-vars-file` **remplace** l'ensemble des variables du service : le fichier est
  donc la source de vérité ; `check_env` empêche d'en déployer un incomplet.

- [ ] **Étape 1 : ajouter la dépendance de développement**

```bash
cd backend
uv add --dev pyyaml
```

- [ ] **Étape 2 : écrire les tests qui échouent**

```python
# backend/tests/test_deploy_assets.py
import shutil
import subprocess
from pathlib import Path

import pytest

from app.tools.check_env import validate_env

ROOT = Path(__file__).resolve().parents[2]

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


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash indisponible")
@pytest.mark.parametrize("script", ["deploy-backend.sh", "export-service-env.sh"])
def test_scripts_have_valid_bash_syntax(script: str) -> None:
    path = ROOT / "scripts" / script
    assert path.exists()
    result = subprocess.run(["bash", "-n", str(path)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_example_env_file_is_valid_and_secret_free() -> None:
    import yaml

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
```
Lancer → ÉCHEC (modules absents).

- [ ] **Étape 3 : `app/tools/check_env.py`**

```python
# backend/app/tools/__init__.py  (fichier vide)
```

```python
# backend/app/tools/check_env.py
"""Vérifie un fichier d'environnement de déploiement AVANT de le pousser sur Cloud Run.

    python -m app.tools.check_env deploy/env.production.yaml

Le fichier remplace l'ensemble des variables du service : un fichier incomplet ou
dangereux (mock activé, secret court…) doit être refusé ici, pas en production.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from unittest import mock

from pydantic import ValidationError

from app.config import Settings

_JSON_KEYS = {"token_enc_keys", "cors_origins"}
_CLOUD_RUN_MANAGED = {"PORT", "K_SERVICE", "K_REVISION", "K_CONFIGURATION"}


def validate_env(mapping: dict[str, str]) -> list[str]:
    """Liste de problèmes (vide si la configuration est valide)."""
    values: dict[str, object] = {}
    for key, raw in mapping.items():
        if key in _CLOUD_RUN_MANAGED:
            continue
        name = key.lower()
        values[name] = json.loads(raw) if name in _JSON_KEYS else raw
    try:
        # On isole le processus de l'environnement réel : seul le fichier compte.
        with mock.patch.dict(os.environ, {}, clear=True):
            Settings(_env_file=None, **values)  # type: ignore[arg-type]
    except (ValidationError, ValueError, json.JSONDecodeError) as exc:
        return [line.strip() for line in str(exc).splitlines() if line.strip()]
    return []


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: python -m app.tools.check_env FICHIER.yaml", file=sys.stderr)
        return 2
    import yaml

    data = yaml.safe_load(Path(argv[1]).read_text(encoding="utf-8")) or {}
    problems = validate_env({str(k): str(v) for k, v in data.items()})
    if problems:
        print("Fichier d'environnement invalide :", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1
    print(f"{argv[1]} : OK ({len(data)} variables)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
```
`pyyaml` est une dépendance de **développement** : en production l'outil n'est lancé
que depuis le poste ou la CI (le script de déploiement utilise le venv local
`backend/.venv`).

- [ ] **Étape 4 : Dockerfile**

Remplacer le commentaire et la ligne `CMD` finaux de `backend/Dockerfile` par :

```dockerfile
EXPOSE 8080

# Cloud Run injecte $PORT (8080 par defaut). Les migrations ne tournent PLUS au
# demarrage : avec plusieurs instances, deux `alembic upgrade head` simultanes se
# marchent dessus. Elles sont executees par un Cloud Run Job avant chaque
# deploiement (voir scripts/deploy-backend.sh et docs/ops/runbook.md).
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8080}"]
```

- [ ] **Étape 5 : `.gitignore` et fichier d'exemple**

Ajouter à `.gitignore` :

```
# Fichiers d'environnement de deploiement (contiennent des secrets)
deploy/env.*.yaml
!deploy/env.example.yaml
```

```yaml
# deploy/env.example.yaml — modele, valeurs factices. Copier vers
# deploy/env.<staging|production>.yaml (ignore par git) et remplacer.
# Lire les valeurs reelles avec scripts/export-service-env.sh.
ENVIRONMENT: "staging"
DATABASE_URL: "postgresql+asyncpg://user:password@host/dbname?ssl=require"
GOOGLE_CLIENT_ID: "000000000000-example.apps.googleusercontent.com"
GOOGLE_CLIENT_SECRET: "example-google-client-secret"
GOOGLE_OAUTH_REDIRECT_URI: "https://staging.example.com/api/v1/auth/google/callback"
GOOGLE_DATA_REDIRECT_URI: "https://staging.example.com/api/v1/connections/google/callback"
GOOGLE_OAUTH_MOCK: "false"
AUDIT_PROBE_MOCK: "false"
ADVISOR_MOCK: "true"
PAGESPEED_API_KEY: ""
ANTHROPIC_API_KEY: ""
FRONTEND_BASE_URL: "https://staging.example.com"
CORS_ORIGINS: '["https://staging.example.com"]'
TOKEN_ENC_KEYS: '{"1":"AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="}'
TOKEN_ENC_ACTIVE_VERSION: "1"
APP_SECRET_KEY: "factice-factice-factice-factice-factice-1234"
SENTRY_DSN: ""
```

- [ ] **Étape 6 : `scripts/export-service-env.sh`**

```bash
#!/usr/bin/env bash
# Exporte les variables d'un service Cloud Run existant vers deploy/env.<env>.yaml
# (ignore par git). A lancer UNE fois par environnement pour amorcer le fichier, puis
# relire et corriger a la main. Les variables devenues inutiles (bases de test, Redis)
# ne sont pas exportees.
#
#   ./scripts/export-service-env.sh production
set -euo pipefail

ENVIRONMENT_NAME="${1:?usage: export-service-env.sh <staging|production>}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROJECT="${GCP_PROJECT:-guiili}"
REGION="${GCP_REGION:-us-central1}"

case "$ENVIRONMENT_NAME" in
  production) SERVICE="backend-guiili" ;;
  staging) SERVICE="backend-guiili-staging" ;;
  *) echo "environnement inconnu : $ENVIRONMENT_NAME" >&2; exit 2 ;;
esac

OUT="$ROOT/deploy/env.${ENVIRONMENT_NAME}.yaml"
if [ -e "$OUT" ]; then
  echo "$OUT existe deja : le supprimer d'abord pour le regenerer." >&2
  exit 1
fi
mkdir -p "$ROOT/deploy"

gcloud run services describe "$SERVICE" --region "$REGION" --project "$PROJECT" \
  --format=json | python -c '
import json, sys
skip = {"DATABASE_URL_TEST", "DATABASE_URL_MIGRATIONS_TEST", "REDIS_URL"}
service = json.load(sys.stdin)
env = service["spec"]["template"]["spec"]["containers"][0].get("env", [])
for item in env:
    name = item["name"]
    if name in skip:
        print("# ignore : " + name, file=sys.stderr)
        continue
    if "value" not in item:
        print("# ATTENTION : " + name + " vient d un secret Cloud Run, a renseigner a la main", file=sys.stderr)
        continue
    print(name + ": " + json.dumps(item["value"]))
' > "$OUT"

chmod 600 "$OUT" 2>/dev/null || true
echo "Ecrit : $OUT (contient des secrets, ne pas committer)."
echo "Verifier ensuite : (cd backend && .venv/Scripts/python.exe -m app.tools.check_env ../deploy/env.${ENVIRONMENT_NAME}.yaml)"
```

- [ ] **Étape 7 : `scripts/deploy-backend.sh`**

```bash
#!/usr/bin/env bash
# Deploie le backend sur Cloud Run : build -> migrations (Cloud Run Job) -> service.
# Un echec de migration arrete tout AVANT de toucher au service.
#
#   ./scripts/deploy-backend.sh staging
#   ./scripts/deploy-backend.sh production
#   ./scripts/deploy-backend.sh production --dry-run    # affiche sans rien executer
#
# Prerequis : gcloud connecte, deploy/env.<env>.yaml (voir deploy/env.example.yaml et
# scripts/export-service-env.sh), depot Artifact Registry `cloud-run-source-deploy`.
set -euo pipefail

ENVIRONMENT_NAME="${1:?usage: deploy-backend.sh <staging|production> [--dry-run]}"
DRY_RUN=""
[ "${2:-}" = "--dry-run" ] && DRY_RUN=1

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROJECT="${GCP_PROJECT:-guiili}"
REGION="${GCP_REGION:-us-central1}"

case "$ENVIRONMENT_NAME" in
  production) SERVICE="backend-guiili" ;;
  staging) SERVICE="backend-guiili-staging" ;;
  *) echo "environnement inconnu : $ENVIRONMENT_NAME" >&2; exit 2 ;;
esac
JOB="${SERVICE}-migrate"
ENV_FILE="$ROOT/deploy/env.${ENVIRONMENT_NAME}.yaml"
TAG="$(git -C "$ROOT" rev-parse --short HEAD)"
IMAGE="${REGION}-docker.pkg.dev/${PROJECT}/cloud-run-source-deploy/${SERVICE}:${TAG}"

run() {
  echo "+ $*"
  if [ -z "$DRY_RUN" ]; then "$@"; fi
}

[ -f "$ENV_FILE" ] || { echo "manquant : $ENV_FILE (voir deploy/env.example.yaml)" >&2; exit 2; }

if ! git -C "$ROOT" diff --quiet || ! git -C "$ROOT" diff --cached --quiet; then
  echo "ATTENTION : des modifications non committees seront absentes de l'image (tag $TAG)." >&2
fi

echo "== 1/5 Verification du fichier d'environnement"
PY="$ROOT/backend/.venv/Scripts/python.exe"
[ -x "$PY" ] || PY="$ROOT/backend/.venv/bin/python"
[ -x "$PY" ] || { echo "venv backend introuvable (uv sync dans backend/)" >&2; exit 2; }
( cd "$ROOT/backend" && "$PY" -m app.tools.check_env "$ENV_FILE" )

echo "== 2/5 Construction de l'image $IMAGE"
run gcloud builds submit "$ROOT/backend" --tag "$IMAGE" --project "$PROJECT" --region "$REGION"

echo "== 3/5 Migrations (Cloud Run Job $JOB)"
run gcloud run jobs deploy "$JOB" --image "$IMAGE" --project "$PROJECT" --region "$REGION" \
  --command alembic --args upgrade,head --env-vars-file "$ENV_FILE" \
  --max-retries 0 --task-timeout 600 --execute-now --wait

echo "== 4/5 Deploiement du service $SERVICE"
run gcloud run deploy "$SERVICE" --image "$IMAGE" --project "$PROJECT" --region "$REGION" \
  --env-vars-file "$ENV_FILE" --allow-unauthenticated \
  --memory 512Mi --cpu 1 --cpu-boost --max-instances 3

echo "== 5/5 Verification"
if [ -n "$DRY_RUN" ]; then
  echo "(dry-run : verification non executee)"; exit 0
fi
URL="$(gcloud run services describe "$SERVICE" --project "$PROJECT" --region "$REGION" --format='value(status.url)')"
for attempt in 1 2 3 4 5; do
  if curl -fsS "$URL/health/db" >/dev/null; then
    echo "OK : $URL/health/db repond (image $TAG)."
    exit 0
  fi
  echo "tentative $attempt/5 : pas encore pret, nouvel essai dans 5 s"
  sleep 5
done
echo "ECHEC : $URL/health/db ne repond pas. Retour arriere :" >&2
echo "  gcloud run services update-traffic $SERVICE --project $PROJECT --region $REGION --to-revisions=<REVISION_PRECEDENTE>=100" >&2
exit 1
```
Rendre les deux scripts exécutables : `git update-index --chmod=+x scripts/*.sh`.

- [ ] **Étape 8 : lancer**

```bash
cd backend
.venv/Scripts/python.exe -m pytest tests/test_deploy_assets.py -v
.venv/Scripts/python.exe -m pytest -W error -q
uv run ruff check app tests
bash -n ../scripts/deploy-backend.sh && bash -n ../scripts/export-service-env.sh
```
Puis, **sans rien exécuter en ligne**, un essai à blanc (nécessite un
`deploy/env.staging.yaml` local copié depuis l'exemple) :
`./scripts/deploy-backend.sh staging --dry-run` doit afficher les commandes
`gcloud builds submit`, `gcloud run jobs deploy … --execute-now --wait` puis
`gcloud run deploy …` sans les lancer.

- [ ] **Étape 9 : commit**

```bash
git add backend scripts deploy .gitignore
git commit -m "feat(prod): migrations hors demarrage (Cloud Run Job) et deploiement scripte avec verification"
```

---

### Tâche 7 : CI GitHub Actions

**Fichiers :**
- Créer : `.github/workflows/ci.yml`, `.github/dependabot.yml`
- Test : `backend/tests/test_ci_workflows.py`

**Interfaces :**
- Consomme : `pyyaml` (Tâche 6).
- Produit : un workflow `CI` déclenché sur chaque PR et sur `main`, avec deux jobs
  (`backend`, `frontend`) ; permissions en lecture seule ; annulation des exécutions
  obsolètes.
- La CI ne peut être exécutée qu'après un push (interdit pendant le plan). Le test ci-
  dessous verrouille la **structure** ; la première exécution réelle a lieu quand le
  propriétaire pousse la branche (voir Tâche 9).

- [ ] **Étape 1 : écrire le test qui échoue**

```python
# backend/tests/test_ci_workflows.py
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
```

Lancer → ÉCHEC (fichiers absents).

- [ ] **Étape 2 : `.github/workflows/ci.yml`**

```yaml
name: CI

on:
  pull_request:
  push:
    branches: [main]

concurrency:
  group: ci-${{ github.ref }}
  cancel-in-progress: true

permissions:
  contents: read

jobs:
  backend:
    runs-on: ubuntu-latest
    timeout-minutes: 25
    services:
      postgres:
        image: postgres:16
        env:
          POSTGRES_USER: cc
          POSTGRES_PASSWORD: cc
          POSTGRES_DB: control_center
        ports: ["5432:5432"]
        options: >-
          --health-cmd "pg_isready -U cc -d control_center"
          --health-interval 5s --health-timeout 5s --health-retries 10
    env:
      ENVIRONMENT: local
      DATABASE_URL: postgresql+asyncpg://cc:cc@localhost:5432/control_center
      DATABASE_URL_TEST: postgresql+asyncpg://cc:cc@localhost:5432/control_center_test
      DATABASE_URL_MIGRATIONS_TEST: postgresql+asyncpg://cc:cc@localhost:5432/control_center_migrations
      REDIS_URL: redis://localhost:6379/0
      TOKEN_ENC_KEYS: '{"1":"AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="}'
      TOKEN_ENC_ACTIVE_VERSION: "1"
      APP_SECRET_KEY: ci-only-secret-never-used-in-a-deployed-environment
      GOOGLE_OAUTH_MOCK: "true"
    defaults:
      run:
        working-directory: backend
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v6
        with:
          enable-cache: true
          cache-dependency-glob: backend/uv.lock
      - name: Installer les dépendances
        run: uv sync --frozen
      - name: Créer les bases jetables
        run: |
          PGPASSWORD=cc psql -h localhost -U cc -d control_center -c "CREATE DATABASE control_center_test"
          PGPASSWORD=cc psql -h localhost -U cc -d control_center -c "CREATE DATABASE control_center_migrations"
      - name: Lint
        run: uv run ruff check app tests
      - name: Migrations à jour (upgrade puis check)
        env:
          ALEMBIC_DATABASE_URL: postgresql+asyncpg://cc:cc@localhost:5432/control_center_migrations
        run: |
          uv run alembic upgrade head
          uv run alembic check
      - name: Tests
        run: uv run pytest -W error -q

  frontend:
    runs-on: ubuntu-latest
    timeout-minutes: 15
    defaults:
      run:
        working-directory: frontend
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: 22
          cache: npm
          cache-dependency-path: frontend/package-lock.json
      - run: npm ci
      - name: Lint (zéro avertissement)
        run: npm run lint
      - name: Build
        run: npm run build
```

- [ ] **Étape 3 : `.github/dependabot.yml`**

```yaml
version: 2
updates:
  - package-ecosystem: uv
    directory: /backend
    schedule: {interval: weekly}
    open-pull-requests-limit: 5
  - package-ecosystem: npm
    directory: /frontend
    schedule: {interval: weekly}
    open-pull-requests-limit: 5
  - package-ecosystem: github-actions
    directory: /
    schedule: {interval: weekly}
```

- [ ] **Étape 4 : lancer**

```bash
cd backend
.venv/Scripts/python.exe -m pytest tests/test_ci_workflows.py -v
.venv/Scripts/python.exe -m pytest -W error -q
```
Vérifier aussi que chaque commande de la CI passe en local dans le même ordre :
`uv run ruff check app tests`, `alembic upgrade head` puis `alembic check` (avec
`ALEMBIC_DATABASE_URL` pointant sur la base des migrations locale), `pytest -W error -q`,
puis `cd ../frontend && npm ci && npm run lint && npm run build`. Toute commande qui
échoue ici échouera en CI : la corriger avant de committer.

- [ ] **Étape 5 : commit**

```bash
git add .github backend/tests/test_ci_workflows.py
git commit -m "ci: pipeline GitHub Actions (lint, migrations, tests backend, lint et build frontend) et Dependabot"
```

---

### Tâche 8 : Runbook, préproduction et déploiement continu

**Fichiers :**
- Créer : `docs/ops/runbook.md`, `.github/workflows/deploy-staging.yml`
- Test : `backend/tests/test_ci_workflows.py` (déjà écrit : le test « aucun secret » couvre
  le nouveau workflow).

**Interfaces :**
- Produit : documentation d'exploitation en français ; workflow de déploiement manuel
  vers la préproduction (`workflow_dispatch` uniquement, environnement GitHub `staging`).
- **Aucune étape de ce plan ne crée l'environnement de préproduction** : elles sont
  listées **[PROPRIÉTAIRE]** dans le runbook et dans le compte rendu.

- [ ] **Étape 1 : `docs/ops/runbook.md`**

Écrire le document avec les sections suivantes, en français, contenu concret et
commandes exactes (aucune section vide) :

1. **Environnements.** Tableau : `local` (docker compose, `scripts/dev.sh`), `staging`
   (service `backend-guiili-staging`, base Neon = branche dédiée), `production` (service
   `backend-guiili`, frontend Vercel `frontend-guiili.vercel.app`, base Neon de
   production). Variables clés par environnement et valeurs interdites hors local
   (référence : `Settings._enforce_environment_rules`).
2. **Déployer.** `./scripts/deploy-backend.sh staging` puis `production` ; ce que fait le
   script (5 étapes) ; `--dry-run` ; le fichier `deploy/env.<env>.yaml` est la source de
   vérité (remplace toutes les variables du service), généré une fois par
   `./scripts/export-service-env.sh` puis relu ; vérification par
   `python -m app.tools.check_env`.
3. **Amorçage unique de la production [PROPRIÉTAIRE].** (a) `./scripts/export-service-env.sh
   production` ; (b) relire le fichier : `DATABASE_URL_TEST`, `DATABASE_URL_MIGRATIONS_TEST`
   et `REDIS_URL` n'y sont volontairement plus (ils pointaient sur la base de
   production) ; (c) `python -m app.tools.check_env deploy/env.production.yaml` ; (d)
   premier déploiement `./scripts/deploy-backend.sh production` : il crée le Cloud Run
   Job de migration et retire les variables obsolètes du service.
4. **Créer la préproduction [PROPRIÉTAIRE].** Créer une branche Neon
   `staging` depuis la production (ou une base vide), copier
   `deploy/env.example.yaml` vers `deploy/env.staging.yaml` et le remplir (URL de la
   base staging, secrets **différents** de la production, `ADVISOR_MOCK: "true"`), puis
   `./scripts/deploy-backend.sh staging` ; créer un projet ou une prévisualisation Vercel
   pointant `BACKEND_ORIGIN` sur l'URL du service de préproduction ; déclarer la
   redirection OAuth de préproduction dans la console Google Cloud.
5. **Retour arrière.** `gcloud run revisions list --service backend-guiili --region
   us-central1 --project guiili` puis `gcloud run services update-traffic backend-guiili
   --to-revisions=<REVISION>=100 --region us-central1 --project guiili`. Règle des
   migrations : **compatibles avec la version précédente du code** (ajouter avant
   d'utiliser, ne supprimer qu'au déploiement suivant), sinon le retour arrière casse.
6. **Lire les logs.** Cloud Logging, requêtes prêtes à l'emploi : erreurs
   `resource.type="cloud_run_revision" AND severity>=ERROR` ; une requête précise
   `jsonPayload.request_id="<id>"` (l'identifiant est dans l'en-tête de réponse
   `x-request-id`) ; lenteurs `jsonPayload.duration_ms>2000`. Cloud Error Reporting
   regroupe les exceptions sans configuration.
7. **Suivi d'erreurs Sentry [PROPRIÉTAIRE, optionnel].** Créer un projet Sentry
   (Python/FastAPI), copier le DSN dans `SENTRY_DSN` du fichier d'environnement,
   redéployer. Sans DSN, rien n'est envoyé. Ce qui n'est jamais envoyé : corps, cookies,
   en-têtes, chaîne de requête (voir `app/observability.py`).
8. **Limites de débit.** Tableau des limites (login 30/15 min par IP et 10 échecs/15 min
   par e-mail, inscription 10/h par IP, réinitialisation 20/h par IP et 5/h par e-mail,
   scan 10/min, headless 3/10 min, conseiller 20 messages/min, création de site 20/h),
   à quoi sert `RATE_LIMIT_ENABLED`, limite **par instance**.
9. **Protection de la branche `main` [PROPRIÉTAIRE].** Réglages GitHub : exiger les
   contrôles `backend` et `frontend` de la CI, exiger une PR, interdire le push forcé.
10. **Secrets.** État actuel (variables d'environnement en clair sur Cloud Run) et
    prochaine étape recommandée : activer Secret Manager
    (`gcloud services enable secretmanager.googleapis.com`), créer un secret par valeur
    sensible (`APP_SECRET_KEY`, `TOKEN_ENC_KEYS`, `GOOGLE_CLIENT_SECRET`,
    `ANTHROPIC_API_KEY`, `DATABASE_URL`) et passer à `--set-secrets` dans le script.
    Rotation : changer `APP_SECRET_KEY` déconnecte tous les utilisateurs ; les clés de
    chiffrement des jetons sont versionnées (`TOKEN_ENC_KEYS` / `TOKEN_ENC_ACTIVE_VERSION`).
11. **Déploiement continu vers la préproduction [PROPRIÉTAIRE].** Prérequis du workflow
    `.github/workflows/deploy-staging.yml` : Workload Identity Federation entre GitHub et
    GCP, compte de service avec les rôles Cloud Run Admin, Cloud Build Editor, Service
    Account User et Artifact Registry Writer, environnement GitHub `staging` avec les
    secrets `GCP_WORKLOAD_IDENTITY_PROVIDER`, `GCP_SERVICE_ACCOUNT` et `STAGING_ENV_YAML`
    (contenu complet de `deploy/env.staging.yaml`).
12. **Incidents.** Liste de contrôle : la base répond (`/health/db`) ; dernière migration
    (`gcloud run jobs executions list --job backend-guiili-migrate`) ; quota Google ou
    PageSpeed ; jeton Google révoqué (`needs_reauth`) ; retour arrière ; contacter.
13. **Hors périmètre du lot 0** (renvoi vers la spec) : séparation `api` / `worker` et
    image API allégée (lot B), Secret Manager effectif, export et suppression RGPD d'un
    workspace, sécurité au niveau des lignes de Postgres.

- [ ] **Étape 2 : `.github/workflows/deploy-staging.yml`**

```yaml
name: Deploy staging

# Déclenchement manuel uniquement. Prérequis : voir docs/ops/runbook.md §11.
on:
  workflow_dispatch:

permissions:
  contents: read
  id-token: write

concurrency:
  group: deploy-staging
  cancel-in-progress: false

jobs:
  deploy:
    runs-on: ubuntu-latest
    timeout-minutes: 30
    environment: staging
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v6
        with:
          enable-cache: true
          cache-dependency-glob: backend/uv.lock
      - name: Installer l'outil de vérification
        working-directory: backend
        run: uv sync --frozen
      - uses: google-github-actions/auth@v2
        with:
          workload_identity_provider: ${{ secrets.GCP_WORKLOAD_IDENTITY_PROVIDER }}
          service_account: ${{ secrets.GCP_SERVICE_ACCOUNT }}
      - uses: google-github-actions/setup-gcloud@v2
      - name: Écrire le fichier d'environnement
        env:
          STAGING_ENV_YAML: ${{ secrets.STAGING_ENV_YAML }}
        run: |
          mkdir -p deploy
          printf '%s\n' "$STAGING_ENV_YAML" > deploy/env.staging.yaml
          chmod 600 deploy/env.staging.yaml
      - name: Déployer
        run: ./scripts/deploy-backend.sh staging
```
Le script cherche `backend/.venv/Scripts/python.exe` puis `backend/.venv/bin/python`
(voir Tâche 6) : sur le runner Linux, le second existe grâce à `uv sync`.

- [ ] **Étape 3 : lancer**

```bash
cd backend
.venv/Scripts/python.exe -m pytest tests/test_ci_workflows.py tests/test_deploy_assets.py -v
.venv/Scripts/python.exe -m pytest -W error -q
```
Relire le runbook : aucune commande ne doit pointer vers une production non
[PROPRIÉTAIRE], aucun secret réel ne doit y figurer.

- [ ] **Étape 4 : commit**

```bash
git add docs/ops .github/workflows/deploy-staging.yml
git commit -m "docs(ops): runbook d'exploitation et workflow de deploiement manuel vers la preproduction"
```

---

### Tâche 9 : Vérification finale et mémoire

**Fichiers :** aucun changement de code attendu.

- [ ] **Étape 1 : suite complète, deux fois, et contrôles**

```bash
cd backend
.venv/Scripts/python.exe -m pytest -W error -q
.venv/Scripts/python.exe -m pytest -W error -q
uv run ruff check app tests
ALEMBIC_DATABASE_URL="$(grep ^DATABASE_URL_MIGRATIONS_TEST .env | cut -d= -f2-)" .venv/Scripts/python.exe -m alembic upgrade head
ALEMBIC_DATABASE_URL="$(grep ^DATABASE_URL_MIGRATIONS_TEST .env | cut -d= -f2-)" .venv/Scripts/python.exe -m alembic check
cd ../frontend && npm run lint && npm run build
```
Attendu : même nombre de tests verts sur les deux passages, 0 erreur, aucun changement
de comportement visible côté frontend.

- [ ] **Étape 2 : vérification de bout en bout en local**

Démarrer l'application (`./scripts/dev.sh`, après avoir vérifié qu'aucun processus ne
tient déjà les ports 8020 et 4000 ; ne tuer que ce qu'on a lancé soi-même) :
1. `curl -i http://127.0.0.1:8020/health` : 200 et en-tête `x-request-id`.
2. La console de l'API affiche une ligne d'accès par requête avec le gabarit de route et
   sans chaîne de requête (`…/auth/google/callback?code=…` n'apparaît nulle part).
3. Depuis le navigateur, se connecter et parcourir `/overview`, `/audit`, `/conseiller`
   : aucune régression, aucune erreur 429 en usage normal.
4. Simuler la production : lancer
   `ENVIRONMENT=production GOOGLE_OAUTH_MOCK=true .venv/Scripts/python.exe -c "from app.config import Settings; Settings()"`
   dans `backend` doit échouer avec un message français listant les problèmes ; avec des
   valeurs valides il doit réussir.
Arrêter les serveurs ensuite.

- [ ] **Étape 3 : mémoire du projet**

Ajouter à
`C:\Users\DELL\.claude\projects\C--Users-DELL-Downloads-Guiili\memory\project-control-center.md`
une section « Lot 0 socle de production » (état, constats de production, décisions,
points ouverts) et mettre à jour `MEMORY.md`.

- [ ] **Étape 4 : compte rendu à l'utilisateur**

Résultat des tests (nombre, deux passages), build et lint, failles d'isolation trouvées
et corrigées (ou absence), et la liste des actions **[PROPRIÉTAIRE]** restantes, dans
l'ordre : (1) pousser la branche pour lancer la CI et vérifier son premier passage ;
(2) amorçage du fichier d'environnement de production et premier déploiement par script,
avec retrait des variables `DATABASE_URL_TEST`, `DATABASE_URL_MIGRATIONS_TEST`,
`REDIS_URL` du service ; (3) protection de `main` ; (4) préproduction ; (5) DSN Sentry
(optionnel) ; (6) Workload Identity Federation pour le déploiement continu (optionnel).
Rappeler que **rien n'a été déployé ni poussé**.
