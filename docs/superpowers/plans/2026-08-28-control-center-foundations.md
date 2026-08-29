# Control Center Marketing Agentique — Fondations techniques : Plan d'implémentation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Initialiser le monorepo `backend/` (FastAPI + SQLAlchemy 2.0 async + Alembic) et `frontend/` (Next.js), avec infra Docker Compose, les 7 tables du modèle de données MVP migrées, et le module de chiffrement AES-256-GCM des refresh tokens Google.

**Architecture:** Monorepo. Backend Python 3.12 géré par `uv`, FastAPI async, SQLAlchemy 2.0 style `Mapped[]`, moteur `asyncpg`, schéma versionné par Alembic (jamais `create_all()` hors tests). Chiffrement des refresh tokens dans un module pur sans dépendance framework, avec registre de clés versionnées et rotation. Frontend Next.js App Router / TypeScript minimal (une page santé). Aucun OAuth Google fonctionnel dans ce plan — seulement les fondations.

**Tech Stack:** Python 3.12, uv, FastAPI, Uvicorn, SQLAlchemy 2.0 (async), asyncpg, Alembic, pydantic-settings, `cryptography`, pytest + pytest-asyncio + httpx ; PostgreSQL 16, Redis 7 (Docker Compose) ; Node 20+, Next.js (App Router), TypeScript, npm.

**Spec:** [docs/superpowers/specs/2026-08-28-control-center-foundations.md](../specs/2026-08-28-control-center-foundations.md)

## Global Constraints

- **Python 3.12**, dépendances gérées par **uv** (`pyproject.toml` + `uv.lock` commités).
- **SQLAlchemy 2.0** style `Mapped[] / mapped_column()`, moteur **async** (`postgresql+asyncpg://`).
- **Node 20 LTS ou +**, frontend **TypeScript**, paquets **npm**, Next.js **App Router**.
- **IDs = UUID v4** (`sqlalchemy.Uuid`, `default=uuid4`, générés côté Python). **Timestamps = `TIMESTAMP WITH TIME ZONE`** (`DateTime(timezone=True)`), `created_at`/`updated_at` en `server_default=func.now()`.
- **Colonnes énumérées : `sa.Enum(PyEnum, native_enum=False, create_constraint=True, name="<nom>")`** → `VARCHAR` + `CHECK` nommé `ck_<table>_<nom>` (pas d'`ENUM` natif Postgres). ⚠️ `create_constraint` vaut `False` par défaut dans SQLAlchemy 2.0 — sans lui, **aucune** contrainte `CHECK` n'est générée et une valeur invalide passe.
- **`MetaData` naming convention obligatoire** (migrations autogénérées stables).
- **Migrations Alembic uniquement** pour le schéma ; `Base.metadata.create_all()` autorisé **seulement** dans les fixtures de test.
- **Refresh tokens Google chiffrés AES-256-GCM au repos.** Access tokens **jamais** persistés.
- **Zéro secret commité.** `.env` gitignore ; `.env.example` documente sans valeurs.
- **Scopes Google MVP (lecture seule)** : `openid`, `email`, `profile`, `https://www.googleapis.com/auth/analytics.readonly`, `https://www.googleapis.com/auth/webmasters.readonly`.
- **Auth applicative : Google OIDC uniquement.** `users.auth_provider` = `'google'`, `users.google_sub` = clé d'identité. Aucun mot de passe stocké.
- **Commits fréquents** : un commit par tâche terminée minimum, conventionnels (`feat:`, `chore:`, `test:`).
- Toutes les commandes backend s'exécutent depuis `backend/` sauf mention contraire.
- **`uv` n'est pas sur le PATH de cette machine** (installé sous Python 3.12 via
  `pip --user`). Partout où le plan écrit `uv ...` (ex. `uv run pytest`,
  `uv sync`, `uv run alembic`), exécuter **`python -m uv ...`**. Si `python`
  n'est pas Python 3.12 dans le shell courant, utiliser `py -3.12 -m uv ...`.
- **Ports Docker non standard sur cette machine** : Postgres est publié sur
  **55432** (5432 = Postgres natif de l'hôte) et Redis sur **6380** (6379 =
  Redis d'un autre projet). Toutes les URLs DB (`.env`, `.env.example`,
  `ALEMBIC_DATABASE_URL`) utilisent `localhost:55432`. `docker compose up -d`
  démarre les deux services proprement. `docker compose stop db` / `start db`
  pour les cycles RED/GREEN.

---

## File Structure

Cible finale (les tâches la construisent incrémentalement) :

```
Guiili/
├── .gitignore                         # T1
├── docker-compose.yml                 # T1
├── README.md                          # T1
├── docker/postgres-init/01-create-databases.sql   # T1
├── docs/…                             # déjà en place
├── backend/
│   ├── pyproject.toml  uv.lock  .env.example       # T2
│   ├── alembic.ini                                 # T7
│   ├── app/
│   │   ├── __init__.py  main.py  config.py         # T2 (main/config), T3 (/health/db)
│   │   ├── db/{__init__,base,session}.py           # T3
│   │   ├── models/{__init__,mixins,enums,user,google_connection,
│   │   │            website,website_google_link,
│   │   │            audit_snapshot,issue_item,audit_log}.py   # T4–T6
│   │   └── security/{__init__,token_crypto}.py     # T8
│   ├── alembic/{env.py,script.py.mako,versions/}   # T7
│   └── tests/
│       ├── __init__.py  conftest.py                # T2 (base), T3 (db fixtures)
│       ├── test_health.py                          # T2
│       ├── test_db_health.py                       # T3
│       ├── test_models_users_connections.py        # T4
│       ├── test_models_websites_links.py           # T5
│       ├── test_models_journal.py                  # T6
│       ├── test_migrations.py                      # T7
│       └── test_token_crypto.py                    # T8
└── frontend/                                       # T9
    ├── package.json … next.config.ts tsconfig.json
    ├── app/{layout,page}.tsx  app/health/page.tsx
    └── lib/api.ts
```

Responsabilités par fichier clé :

- `app/config.py` — chargement/validation de la configuration d'environnement (pydantic-settings). Source unique de vérité pour URLs DB, secrets OAuth, clés de chiffrement.
- `app/db/base.py` — `Base` déclarative + `MetaData` avec naming convention. Rien d'autre.
- `app/db/session.py` — moteur async, `async_sessionmaker`, dépendance FastAPI `get_session`.
- `app/models/enums.py` — toutes les énumérations métier (`StrEnum`).
- `app/models/mixins.py` — `UUIDPrimaryKeyMixin`, `TimestampMixin`.
- `app/models/<entité>.py` — une entité par fichier, relations comprises.
- `app/models/__init__.py` — importe tous les modèles pour que `Base.metadata` soit complet (Alembic + tests).
- `app/security/token_crypto.py` — chiffrement AES-256-GCM, registre de clés versionnées, rotation, exceptions. **Aucun import de SQLAlchemy/FastAPI.**
- `alembic/env.py` — pont Alembic ↔ `Base.metadata`, exécution async, URL depuis `ALEMBIC_DATABASE_URL` ou la config.

---

## Task 1: Scaffolding du monorepo + infra Docker Compose

**Files:**
- Create: `.gitignore`
- Create: `docker-compose.yml`
- Create: `docker/postgres-init/01-create-databases.sql`
- Create: `README.md`

**Interfaces:**
- Consumes: rien.
- Produces: bases `control_center`, `control_center_test`, `control_center_migrations` accessibles sur `localhost:55432` (user `cc`, mot de passe `cc`) ; Redis sur `localhost:6380`. Ports non standard car 5432/6379 sont déjà pris sur la machine de dev (Postgres natif + Redis d'un autre projet). Ces valeurs sont réutilisées par `backend/.env.example` (T2).

- [ ] **Step 1: Créer `.gitignore`**

```gitignore
# Python
__pycache__/
*.py[cod]
.venv/
.pytest_cache/
.ruff_cache/
*.egg-info/

# Env & secrets
.env
.env.local
.env.*.local

# Node
node_modules/
.next/
out/
next-env.d.ts

# OS / IDE
.DS_Store
.idea/
.vscode/
```

- [ ] **Step 2: Créer `docker/postgres-init/01-create-databases.sql`**

Le conteneur `postgres` exécute automatiquement les `*.sql` de `/docker-entrypoint-initdb.d/` au premier démarrage (base vide). La base `control_center` est déjà créée par `POSTGRES_DB` ; on ajoute les deux bases de test.

```sql
CREATE DATABASE control_center_test;
CREATE DATABASE control_center_migrations;
```

- [ ] **Step 3: Créer `docker-compose.yml`**

```yaml
# 5432 / 6379 sont déjà pris sur la machine de dev (Postgres natif + Redis d'un
# autre projet) → on publie sur 55432 / 6380. backend/.env(.example) suivent.
services:
  db:
    image: postgres:16
    environment:
      POSTGRES_USER: cc
      POSTGRES_PASSWORD: cc
      POSTGRES_DB: control_center
    ports:
      - "55432:5432"
    volumes:
      - pgdata:/var/lib/postgresql/data
      - ./docker/postgres-init:/docker-entrypoint-initdb.d:ro
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U cc -d control_center"]
      interval: 5s
      timeout: 5s
      retries: 10

  redis:
    image: redis:7
    ports:
      - "6380:6379"
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      timeout: 5s
      retries: 10

volumes:
  pgdata:
```

> Volume nommé `pgdata` (pas de bind mount `./.pgdata`) : évite les problèmes de
> permissions du répertoire PGDATA sous Docker Desktop / Windows. Pour repartir
> de zéro (ré-exécuter les scripts d'init) : `docker compose down -v`.

- [ ] **Step 4: Créer `README.md`**

```markdown
# Control Center Marketing Agentique

Plateforme d'audit marketing (SEO / GA4 / Core Web Vitals) multi-comptes Google,
en lecture seule. Voir `docs/reference/plan-v3.md` pour la vision produit et
`docs/superpowers/specs/` pour les specs techniques.

## Prérequis

- Docker + Docker Compose
- Python 3.12 + [uv](https://docs.astral.sh/uv/)
- Node 20+

## Démarrage local

```bash
docker compose up -d                 # PostgreSQL + Redis
cd backend
cp .env.example .env                 # puis renseigner les valeurs
uv sync
uv run alembic upgrade head
uv run uvicorn app.main:app --reload  # http://localhost:8000/health
```

```bash
cd frontend
cp .env.example .env.local
npm install
npm run dev                           # http://localhost:3000
```

## Tests

```bash
cd backend && uv run pytest
```
```

- [ ] **Step 5: Démarrer l'infra et vérifier**

Run: `docker compose up -d`
Puis: `docker compose ps`
Expected: services `db` et `redis` à l'état `running (healthy)` sous ~15 s.

- [ ] **Step 6: Vérifier que les 3 bases existent**

Run: `docker compose exec db psql -U cc -d control_center -c "\l"`
Expected: la liste contient les 3 bases `control_center`, `control_center_test`, `control_center_migrations`.

> Si les bases de test manquent : le volume `pgdata` a été créé lors d'un run
> précédent (avant l'ajout du script d'init). `docker compose down -v` puis
> `docker compose up -d` pour forcer la ré-exécution des scripts d'init.

- [ ] **Step 7: Committer**

Le dépôt git est déjà initialisé et la branche de travail est `feat/foundations`
(le contrôleur s'en est chargé). Committer les nouveaux fichiers d'infra :

```bash
git add .gitignore docker-compose.yml docker/ README.md
git commit -m "chore: scaffold monorepo + docker compose infra"
```

> `.gitignore` existe déjà (version bootstrap minimale) : le remplacer par le
> contenu du Step 1, c'est une modification et non une création.

---

## Task 2: Backend — init projet uv, configuration, endpoint /health

**Files:**
- Create: `backend/pyproject.toml`
- Create: `backend/.env.example`
- Create: `backend/app/__init__.py` (vide)
- Create: `backend/app/config.py`
- Create: `backend/app/main.py`
- Create: `backend/tests/__init__.py` (vide)
- Create: `backend/tests/conftest.py`
- Create: `backend/tests/test_health.py`

**Interfaces:**
- Consumes: identifiants Postgres/Redis de T1.
- Produces:
  - `app.config.Settings` (pydantic-settings) avec au minimum : `environment: str`, `database_url: str`, `database_url_test: str`, `database_url_migrations_test: str`, `redis_url: str`, `google_client_id: str`, `google_client_secret: str`, `google_oauth_redirect_uri: str`, `token_enc_keys: dict[int, str]`, `token_enc_active_version: int`, `app_secret_key: str`.
  - `app.config.get_settings() -> Settings` (mémoïsé via `functools.lru_cache`).
  - `app.main.app` — instance `FastAPI`.
  - `GET /health` → `200 {"status": "ok"}`.
  - Fixture pytest `client` (httpx `AsyncClient` monté sur `app`).

- [ ] **Step 1: Créer `backend/pyproject.toml`**

```toml
[project]
name = "control-center-backend"
version = "0.1.0"
requires-python = "==3.12.*"
dependencies = [
    "fastapi>=0.115",
    "uvicorn[standard]>=0.34",
    "sqlalchemy[asyncio]>=2.0.36",
    "asyncpg>=0.30",
    "alembic>=1.14",
    "pydantic-settings>=2.7",
    "cryptography>=44.0",
]

[dependency-groups]
dev = [
    "pytest>=8.3",
    "pytest-asyncio>=0.25",
    "httpx>=0.28",
    "ruff>=0.9",
]

[tool.pytest.ini_options]
asyncio_mode = "auto"
asyncio_default_fixture_loop_scope = "function"
testpaths = ["tests"]

[tool.ruff]
line-length = 100
target-version = "py312"
```

- [ ] **Step 2: Synchroniser l'environnement**

Run: `cd backend && uv sync`
Expected: crée `.venv/` et `uv.lock`. Aucune erreur de résolution.

- [ ] **Step 3: Créer `backend/.env.example`**

```
ENVIRONMENT=local
# Docker Compose publie Postgres sur 55432 et Redis sur 6380 (voir docker-compose.yml)
DATABASE_URL=postgresql+asyncpg://cc:cc@localhost:55432/control_center
DATABASE_URL_TEST=postgresql+asyncpg://cc:cc@localhost:55432/control_center_test
DATABASE_URL_MIGRATIONS_TEST=postgresql+asyncpg://cc:cc@localhost:55432/control_center_migrations
REDIS_URL=redis://localhost:6380/0

GOOGLE_CLIENT_ID=
GOOGLE_CLIENT_SECRET=
GOOGLE_OAUTH_REDIRECT_URI=http://localhost:8000/auth/google/callback

# python -c "import os,base64;print(base64.b64encode(os.urandom(32)).decode())"
TOKEN_ENC_KEYS={"1":"REMPLACER_PAR_UNE_CLE_BASE64_DE_32_OCTETS"}
TOKEN_ENC_ACTIVE_VERSION=1

APP_SECRET_KEY=REMPLACER
```

- [ ] **Step 4: Créer `backend/.env` de développement**

```bash
cd backend && cp .env.example .env
```
Puis générer une vraie clé et remplacer la valeur de `TOKEN_ENC_KEYS` dans `.env` :
```bash
uv run python -c "import os,base64;print(base64.b64encode(os.urandom(32)).decode())"
```
Mettre aussi `APP_SECRET_KEY` à une valeur aléatoire quelconque. Laisser les `GOOGLE_*` vides pour l'instant.

- [ ] **Step 5: Créer `backend/app/__init__.py` et `backend/tests/__init__.py`**

Deux fichiers vides.

- [ ] **Step 6: Créer `backend/app/config.py`**

```python
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

    app_secret_key: str = "dev-only-not-secret"


@lru_cache
def get_settings() -> Settings:
    return Settings()
```

- [ ] **Step 7: Créer `backend/app/main.py`**

```python
from fastapi import FastAPI

app = FastAPI(title="Control Center Marketing Agentique", version="0.1.0")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
```

- [ ] **Step 8: Créer `backend/tests/conftest.py` (version de base)**

```python
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest_asyncio.fixture
async def client() -> AsyncClient:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
```

- [ ] **Step 9: Écrire le test qui échoue — `backend/tests/test_health.py`**

```python
from httpx import AsyncClient


async def test_health_returns_ok(client: AsyncClient) -> None:
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
```

- [ ] **Step 10: Lancer le test — attendu : PASS**

Run: `cd backend && uv run pytest tests/test_health.py -v`
Expected: `test_health_returns_ok PASSED`.
(Le test valide en réalité que l'app se charge, donc que `config.py` lit bien `.env`. S'il échoue avec `ValidationError`, une variable manque dans `.env`.)

- [ ] **Step 11: Vérifier le lint et committer**

```bash
cd backend && uv run ruff check .
git add backend/pyproject.toml backend/uv.lock backend/.env.example backend/app backend/tests
git commit -m "feat(backend): uv project init, settings, /health endpoint"
```

---

## Task 3: Backend — couche base de données async + /health/db

**Files:**
- Create: `backend/app/db/__init__.py` (vide)
- Create: `backend/app/db/base.py`
- Create: `backend/app/db/session.py`
- Modify: `backend/app/main.py` (ajout route `/health/db`)
- Modify: `backend/tests/conftest.py` (fixtures `engine`, `db_session`, override de `get_session`)
- Create: `backend/tests/test_db_health.py`

**Interfaces:**
- Consumes: `app.config.get_settings()` (T2).
- Produces:
  - `app.db.base.Base` — `DeclarativeBase` avec `metadata` conventionnée.
  - `app.db.session.get_session()` — dépendance FastAPI, `async` generator yieldant `AsyncSession`.
  - `app.db.session.build_engine(url: str) -> AsyncEngine` — factory réutilisée par les tests.
  - `GET /health/db` → `200 {"database": "ok"}` si `SELECT 1` réussit.
  - Fixtures pytest `engine` (crée/détruit le schéma sur `database_url_test`) et `db_session` (transaction par test, rollback).

- [ ] **Step 1: Créer `backend/app/db/__init__.py`** (vide)

- [ ] **Step 2: Créer `backend/app/db/base.py`**

```python
from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)
```

- [ ] **Step 3: Créer `backend/app/db/session.py`**

```python
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import get_settings


def build_engine(url: str) -> AsyncEngine:
    return create_async_engine(url, pool_pre_ping=True, future=True)


engine: AsyncEngine = build_engine(get_settings().database_url)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session
```

- [ ] **Step 4: Modifier `backend/app/main.py` — ajouter `/health/db`**

Remplacer le contenu par :

```python
from fastapi import Depends, FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session

app = FastAPI(title="Control Center Marketing Agentique", version="0.1.0")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/health/db")
async def health_db(session: AsyncSession = Depends(get_session)) -> dict[str, str]:
    await session.execute(text("SELECT 1"))
    return {"database": "ok"}
```

- [ ] **Step 5: Remplacer `backend/tests/conftest.py`**

```python
from collections.abc import AsyncGenerator

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import app.models  # noqa: F401 — enregistre tous les modèles dans Base.metadata
from app.config import get_settings
from app.db.base import Base
from app.db.session import build_engine, get_session
from app.main import app


@pytest_asyncio.fixture
async def engine() -> AsyncGenerator:
    eng = build_engine(get_settings().database_url_test)
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await eng.dispose()


@pytest_asyncio.fixture
async def db_session(engine) -> AsyncGenerator[AsyncSession, None]:
    conn = await engine.connect()
    trans = await conn.begin()
    # join_transaction_mode="create_savepoint" : la session travaille dans un
    # SAVEPOINT, donc une IntegrityError levée par un test (ex. violation de
    # contrainte UNIQUE testée via pytest.raises) revient au savepoint sans
    # « empoisonner » la transaction externe — le trans.rollback() du teardown
    # reste propre (pas de SAWarning "transaction already deassociated").
    session_maker = async_sessionmaker(
        bind=conn,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )
    session = session_maker()
    try:
        yield session
    finally:
        await session.close()
        await trans.rollback()
        await conn.close()


@pytest_asyncio.fixture
async def client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    async def _override_get_session() -> AsyncGenerator[AsyncSession, None]:
        yield db_session

    app.dependency_overrides[get_session] = _override_get_session
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()
```

> Note : `import app.models` échoue tant que T4 n'a pas créé `app/models/__init__.py`. Créer immédiatement un `backend/app/models/__init__.py` vide dans cette tâche (il sera rempli en T4–T6) pour ne pas casser `conftest.py`.

- [ ] **Step 6: Créer `backend/app/models/__init__.py`** (vide pour l'instant)

- [ ] **Step 7: Écrire le test qui échoue — `backend/tests/test_db_health.py`**

```python
from httpx import AsyncClient


async def test_health_db_ok(client: AsyncClient) -> None:
    response = await client.get("/health/db")
    assert response.status_code == 200
    assert response.json() == {"database": "ok"}
```

- [ ] **Step 8: Lancer le test — vérifier qu'il échoue d'abord si l'infra est down**

Run: `docker compose stop db && cd backend && uv run pytest tests/test_db_health.py -v`
Expected: FAIL (connexion refusée). Cela prouve que le test touche réellement la base.

- [ ] **Step 9: Relancer avec l'infra up — attendu : PASS**

Run: `docker compose start db && cd backend && uv run pytest -v`
Expected: `test_health_returns_ok` et `test_health_db_ok` PASSED.

- [ ] **Step 10: Lint + commit**

```bash
cd backend && uv run ruff check .
git add backend/app backend/tests
git commit -m "feat(backend): async DB layer + /health/db"
```

---

## Task 4: Modèles — énumérations, mixins, `users`, `google_connections`

**Files:**
- Create: `backend/app/models/enums.py`
- Create: `backend/app/models/mixins.py`
- Create: `backend/app/models/user.py`
- Create: `backend/app/models/google_connection.py`
- Modify: `backend/app/models/__init__.py`
- Create: `backend/tests/test_models_users_connections.py`

**Interfaces:**
- Consumes: `app.db.base.Base`, fixtures `db_session` (T3).
- Produces (noms/signatures repris par T5–T7) :
  - `app.models.enums.ConnectionStatus` : `ACTIVE`, `NEEDS_REAUTH`, `REVOKED` (StrEnum).
  - `app.models.mixins.UUIDPrimaryKeyMixin` (colonne `id: Mapped[UUID]`), `TimestampMixin` (`created_at`, `updated_at`).
  - `app.models.user.User` — table `users`. Champs : `id, email, auth_provider, google_sub, display_name, created_at, updated_at`. Relation `google_connections: Mapped[list[GoogleConnection]]` (avec `passive_deletes=True`). La relation `websites` est ajoutée en T5 (le modèle `Website` n'existe pas encore).
  - `app.models.google_connection.GoogleConnection` — table `google_connections`. Champs : `id, user_id, google_account_email, google_sub, granted_scopes (list[str]), refresh_token_encrypted (bytes), encryption_key_version (int), status (ConnectionStatus), created_at, updated_at, last_refreshed_at`. Relation `user: Mapped[User]`.

- [ ] **Step 1: Créer `backend/app/models/enums.py`**

```python
from enum import StrEnum


class ConnectionStatus(StrEnum):
    ACTIVE = "active"
    NEEDS_REAUTH = "needs_reauth"
    REVOKED = "revoked"


class ResourceType(StrEnum):
    GA4_PROPERTY = "ga4_property"
    GTM_CONTAINER = "gtm_container"
    GSC_SITE = "gsc_site"


class SnapshotSource(StrEnum):
    PAGESPEED = "pagespeed"
    GA4 = "ga4"
    GSC = "gsc"
    COMPOSITE = "composite"


class IssueCategory(StrEnum):
    SEO = "seo"
    ANALYTICS = "analytics"
    CWV = "cwv"
    TRACKING = "tracking"
    OTHER = "other"


class IssueSeverity(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class IssueStatus(StrEnum):
    TODO = "todo"
    IN_PROGRESS = "in_progress"
    FIXED = "fixed"
    DISMISSED = "dismissed"


class AuditResult(StrEnum):
    SUCCESS = "success"
    ERROR = "error"
```

- [ ] **Step 2: Créer `backend/app/models/mixins.py`**

```python
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column


class UUIDPrimaryKeyMixin:
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
```

- [ ] **Step 3: Créer `backend/app/models/user.py`**

> ⚠️ La relation `websites` **n'est pas** dans cette version : le modèle
> `Website` n'existe qu'en T5, et SQLAlchemy résout les cibles de relations à
> la configuration des mappers (au premier `flush`), ce qui casserait les tests
> de T4. T5 ajoutera `websites` à ce fichier. `passive_deletes=True` +
> `ondelete="CASCADE"` (côté FK) : la suppression en cascade est faite par
> Postgres, pas par un lazy-load ORM (impossible en async).

```python
from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.google_connection import GoogleConnection


class User(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False)
    auth_provider: Mapped[str] = mapped_column(
        String(32), nullable=False, default="google"
    )
    google_sub: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)

    google_connections: Mapped[list[GoogleConnection]] = relationship(
        back_populates="user", cascade="all, delete-orphan", passive_deletes=True
    )
```

- [ ] **Step 4: Créer `backend/app/models/google_connection.py`**

```python
from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import (
    ARRAY,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.enums import ConnectionStatus
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.user import User


class GoogleConnection(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "google_connections"
    __table_args__ = (
        # un utilisateur ne lie pas deux fois la même identité Google
        UniqueConstraint("user_id", "google_sub", name="user_google_sub"),
    )

    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    google_account_email: Mapped[str] = mapped_column(String(320), nullable=False)
    google_sub: Mapped[str] = mapped_column(String(255), nullable=False)
    granted_scopes: Mapped[list[str]] = mapped_column(
        ARRAY(String), nullable=False
    )
    refresh_token_encrypted: Mapped[bytes] = mapped_column(
        LargeBinary, nullable=False
    )
    encryption_key_version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[ConnectionStatus] = mapped_column(
        Enum(ConnectionStatus, native_enum=False, create_constraint=True, name="connection_status", length=32),
        nullable=False,
        default=ConnectionStatus.ACTIVE,
    )
    last_refreshed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    user: Mapped[User] = relationship(back_populates="google_connections")
```

- [ ] **Step 5: Modifier `backend/app/models/__init__.py` (version T4)**

`__init__.py` grandit à chaque tâche (T4 : 2 modèles, T5 : +2, T6 : +3). Ne
mettre que ce qui existe, sinon `import app.models` casse tout `conftest.py`.
Version T4 exacte :

```python
from app.models.google_connection import GoogleConnection
from app.models.user import User

__all__ = ["GoogleConnection", "User"]
```

- [ ] **Step 6: Écrire les tests qui échouent — `backend/tests/test_models_users_connections.py`**

```python
import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import ConnectionStatus
from app.models.google_connection import GoogleConnection
from app.models.user import User


async def _make_user(session: AsyncSession, sub: str = "sub-1") -> User:
    user = User(email=f"{sub}@example.com", google_sub=sub)
    session.add(user)
    await session.flush()
    return user


async def test_user_defaults(db_session: AsyncSession) -> None:
    user = await _make_user(db_session)
    assert user.auth_provider == "google"
    assert user.id is not None
    assert user.created_at is not None


async def test_connection_status_defaults_active(db_session: AsyncSession) -> None:
    user = await _make_user(db_session)
    conn = GoogleConnection(
        user_id=user.id,
        google_account_email="acct@example.com",
        google_sub="g-sub-1",
        granted_scopes=["openid", "email"],
        refresh_token_encrypted=b"\x00\x01",
        encryption_key_version=1,
    )
    db_session.add(conn)
    await db_session.flush()
    assert conn.status == ConnectionStatus.ACTIVE


async def test_connection_unique_user_google_sub(db_session: AsyncSession) -> None:
    user = await _make_user(db_session)
    common = {
        "user_id": user.id,
        "google_account_email": "a@example.com",
        "google_sub": "dup-sub",
        "granted_scopes": ["openid"],
        "refresh_token_encrypted": b"x",
        "encryption_key_version": 1,
    }
    db_session.add(GoogleConnection(**common))
    await db_session.flush()
    db_session.add(GoogleConnection(**common))
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_user_cascade_deletes_connections(db_session: AsyncSession) -> None:
    user = await _make_user(db_session)
    db_session.add(
        GoogleConnection(
            user_id=user.id,
            google_account_email="a@example.com",
            google_sub="c-sub",
            granted_scopes=["openid"],
            refresh_token_encrypted=b"x",
            encryption_key_version=1,
        )
    )
    await db_session.flush()
    await db_session.delete(user)
    await db_session.flush()
    remaining = (await db_session.execute(select(GoogleConnection))).scalars().all()
    assert remaining == []
```

- [ ] **Step 7: Lancer — attendu : PASS**

Run: `cd backend && uv run pytest tests/test_models_users_connections.py -v`
Expected: 4 tests PASSED.
(`test_user_cascade_deletes_connections` : le `passive_deletes=True` sur
`User.google_connections` + `ondelete="CASCADE"` sur le FK délèguent la
suppression à Postgres — pas de lazy-load ORM, ce qui serait impossible en
async. Si `MissingGreenlet` apparaît, c'est que `passive_deletes=True` a été
oublié sur la relation.)

- [ ] **Step 8: Lint + commit**

```bash
cd backend && uv run ruff check .
git add backend/app/models backend/tests/test_models_users_connections.py
git commit -m "feat(models): enums, mixins, User, GoogleConnection"
```

---

## Task 5: Modèles — `websites`, `website_google_links`

**Files:**
- Create: `backend/app/models/website.py`
- Create: `backend/app/models/website_google_link.py`
- Modify: `backend/app/models/user.py` (ajouter la relation `websites`)
- Modify: `backend/app/models/__init__.py` (ajouter `Website`, `WebsiteGoogleLink`)
- Create: `backend/tests/test_models_websites_links.py`

**Interfaces:**
- Consumes: `Base`, `User` (T4), `GoogleConnection` (T4), fixtures T3.
- Produces :
  - `app.models.website.Website` — table `websites`. Champs : `id, user_id, domain, display_name, created_at, updated_at`. Relations : `user: Mapped[User]`, `google_links: Mapped[list[WebsiteGoogleLink]]`. Contrainte `UNIQUE (user_id, domain)`.
  - `app.models.website_google_link.WebsiteGoogleLink` — table `website_google_links`. Champs : `id, website_id, google_connection_id, resource_type (ResourceType), resource_id (str), resource_display_name (str|None), linked_at (datetime)`. Contrainte `UNIQUE (website_id, resource_type, resource_id)`.

- [ ] **Step 1: Créer `backend/app/models/website.py`**

```python
from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.user import User
    from app.models.website_google_link import WebsiteGoogleLink


class Website(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "websites"
    __table_args__ = (UniqueConstraint("user_id", "domain", name="user_domain"),)

    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    domain: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)

    user: Mapped[User] = relationship(back_populates="websites")
    google_links: Mapped[list[WebsiteGoogleLink]] = relationship(
        back_populates="website", cascade="all, delete-orphan", passive_deletes=True
    )
```

- [ ] **Step 2: Créer `backend/app/models/website_google_link.py`**

```python
from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import (
    DateTime,
    Enum,
    ForeignKey,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.enums import ResourceType
from app.models.mixins import UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.website import Website


class WebsiteGoogleLink(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "website_google_links"
    __table_args__ = (
        UniqueConstraint(
            "website_id", "resource_type", "resource_id", name="website_resource"
        ),
    )

    website_id: Mapped[UUID] = mapped_column(
        ForeignKey("websites.id", ondelete="CASCADE"), nullable=False, index=True
    )
    google_connection_id: Mapped[UUID] = mapped_column(
        ForeignKey("google_connections.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    resource_type: Mapped[ResourceType] = mapped_column(
        Enum(ResourceType, native_enum=False, create_constraint=True, name="resource_type", length=32),
        nullable=False,
    )
    resource_id: Mapped[str] = mapped_column(String(255), nullable=False)
    resource_display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    linked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    website: Mapped[Website] = relationship(back_populates="google_links")
```

- [ ] **Step 3: Modifier `backend/app/models/user.py` — ajouter la relation `websites`**

Ajouter l'import `TYPE_CHECKING` de `Website` et la relation. Résultat :

```python
if TYPE_CHECKING:
    from app.models.google_connection import GoogleConnection
    from app.models.website import Website
```

et dans la classe `User`, après `google_connections` :

```python
    websites: Mapped[list[Website]] = relationship(
        back_populates="user", cascade="all, delete-orphan", passive_deletes=True
    )
```

- [ ] **Step 4: Modifier `backend/app/models/__init__.py` (version T5)**

```python
from app.models.google_connection import GoogleConnection
from app.models.user import User
from app.models.website import Website
from app.models.website_google_link import WebsiteGoogleLink

__all__ = ["GoogleConnection", "User", "Website", "WebsiteGoogleLink"]
```

- [ ] **Step 5: Écrire les tests qui échouent — `backend/tests/test_models_websites_links.py`**

```python
import pytest
from sqlalchemy import select
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import ResourceType
from app.models.google_connection import GoogleConnection
from app.models.user import User
from app.models.website import Website
from app.models.website_google_link import WebsiteGoogleLink


async def _seed(session: AsyncSession) -> tuple[User, GoogleConnection]:
    user = User(email="u@example.com", google_sub="sub-w")
    session.add(user)
    await session.flush()
    conn = GoogleConnection(
        user_id=user.id,
        google_account_email="acct@example.com",
        google_sub="g-w",
        granted_scopes=["openid"],
        refresh_token_encrypted=b"x",
        encryption_key_version=1,
    )
    session.add(conn)
    await session.flush()
    return user, conn


async def test_website_unique_user_domain(db_session: AsyncSession) -> None:
    user, _ = await _seed(db_session)
    db_session.add(Website(user_id=user.id, domain="ex.com", display_name="Ex"))
    await db_session.flush()
    db_session.add(Website(user_id=user.id, domain="ex.com", display_name="Ex2"))
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_link_multi_connection_per_website(db_session: AsyncSession) -> None:
    user, conn = await _seed(db_session)
    site = Website(user_id=user.id, domain="ex.com", display_name="Ex")
    db_session.add(site)
    await db_session.flush()
    db_session.add_all(
        [
            WebsiteGoogleLink(
                website_id=site.id,
                google_connection_id=conn.id,
                resource_type=ResourceType.GA4_PROPERTY,
                resource_id="properties/123",
            ),
            WebsiteGoogleLink(
                website_id=site.id,
                google_connection_id=conn.id,
                resource_type=ResourceType.GSC_SITE,
                resource_id="sc-domain:ex.com",
            ),
        ]
    )
    await db_session.flush()
    links = (await db_session.execute(select(WebsiteGoogleLink))).scalars().all()
    assert {link.resource_type for link in links} == {
        ResourceType.GA4_PROPERTY,
        ResourceType.GSC_SITE,
    }


async def test_link_rejects_invalid_resource_type(db_session: AsyncSession) -> None:
    user, conn = await _seed(db_session)
    site = Website(user_id=user.id, domain="ex.com", display_name="Ex")
    db_session.add(site)
    await db_session.flush()
    db_session.add(
        WebsiteGoogleLink(
            website_id=site.id,
            google_connection_id=conn.id,
            resource_type="not_a_type",  # viole le CHECK
            resource_id="x",
        )
    )
    with pytest.raises((IntegrityError, DBAPIError)):
        await db_session.flush()


async def test_website_delete_cascades_links(db_session: AsyncSession) -> None:
    user, conn = await _seed(db_session)
    site = Website(user_id=user.id, domain="ex.com", display_name="Ex")
    db_session.add(site)
    await db_session.flush()
    db_session.add(
        WebsiteGoogleLink(
            website_id=site.id,
            google_connection_id=conn.id,
            resource_type=ResourceType.GA4_PROPERTY,
            resource_id="properties/123",
        )
    )
    await db_session.flush()
    await db_session.delete(site)
    await db_session.flush()
    links = (await db_session.execute(select(WebsiteGoogleLink))).scalars().all()
    assert links == []
```

- [ ] **Step 6: Lancer — attendu : PASS**

Run: `cd backend && uv run pytest tests/test_models_websites_links.py -v`
Expected: 4 tests PASSED.

- [ ] **Step 7: Relancer T4 pour non-régression**

Run: `cd backend && uv run pytest tests/test_models_users_connections.py -v`
Expected: 4 tests toujours PASSED (l'ajout de la relation `websites` sur `User`
ne casse rien).

- [ ] **Step 8: Lint + commit**

```bash
cd backend && uv run ruff check .
git add backend/app/models backend/tests/test_models_websites_links.py
git commit -m "feat(models): Website, WebsiteGoogleLink"
```

---

## Task 6: Modèles — `audit_snapshots`, `issue_items`, `audit_log`

**Files:**
- Create: `backend/app/models/audit_snapshot.py`
- Create: `backend/app/models/issue_item.py`
- Create: `backend/app/models/audit_log.py`
- Modify: `backend/app/models/__init__.py` (ajouter les 3)
- Create: `backend/tests/test_models_journal.py`

**Interfaces:**
- Consumes: `Base`, `User` (T4), `Website` (T5), enums `SnapshotSource, IssueCategory, IssueSeverity, IssueStatus, AuditResult` (T4).
- Produces :
  - `app.models.audit_snapshot.AuditSnapshot` — table `audit_snapshots`. Champs : `id, website_id, captured_at (datetime), source (SnapshotSource), metrics (dict, JSONB), created_at`. Index `(website_id, captured_at)`.
  - `app.models.issue_item.IssueItem` — table `issue_items`. Champs : `id, website_id, title, description, category, severity, status (défaut TODO), fingerprint, detected_at, resolved_at (None), source_snapshot_id (UUID|None), created_at, updated_at`. Contrainte `UNIQUE (website_id, fingerprint)`. FK `source_snapshot_id` → `audit_snapshots.id` ON DELETE SET NULL.
  - `app.models.audit_log.AuditLog` — table `audit_log`. Champs : `id, user_id (UUID|None), google_connection_id (UUID|None), action, resource_type (None), resource_id (None), request_payload_hash (None), result (AuditResult), error_message (None), ip_address (None), created_at`. FKs en ON DELETE SET NULL. Index `(user_id, created_at)`.

- [ ] **Step 1: Créer `backend/app/models/audit_snapshot.py`**

```python
from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import DateTime, Enum, ForeignKey, Index, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.enums import SnapshotSource
from app.models.mixins import UUIDPrimaryKeyMixin


class AuditSnapshot(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "audit_snapshots"
    __table_args__ = (
        Index("ix_audit_snapshots_website_captured", "website_id", "captured_at"),
    )

    website_id: Mapped[UUID] = mapped_column(
        ForeignKey("websites.id", ondelete="CASCADE"), nullable=False
    )
    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    source: Mapped[SnapshotSource] = mapped_column(
        Enum(SnapshotSource, native_enum=False, create_constraint=True, name="snapshot_source", length=32),
        nullable=False,
    )
    metrics: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
```

- [ ] **Step 2: Créer `backend/app/models/issue_item.py`**

```python
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    DateTime,
    Enum,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.enums import IssueCategory, IssueSeverity, IssueStatus
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class IssueItem(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "issue_items"
    __table_args__ = (
        UniqueConstraint("website_id", "fingerprint", name="website_fingerprint"),
    )

    website_id: Mapped[UUID] = mapped_column(
        ForeignKey("websites.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[IssueCategory] = mapped_column(
        Enum(IssueCategory, native_enum=False, create_constraint=True, name="issue_category", length=32),
        nullable=False,
    )
    severity: Mapped[IssueSeverity] = mapped_column(
        Enum(IssueSeverity, native_enum=False, create_constraint=True, name="issue_severity", length=32),
        nullable=False,
    )
    status: Mapped[IssueStatus] = mapped_column(
        Enum(IssueStatus, native_enum=False, create_constraint=True, name="issue_status", length=32),
        nullable=False,
        default=IssueStatus.TODO,
    )
    fingerprint: Mapped[str] = mapped_column(String(255), nullable=False)
    detected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    source_snapshot_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("audit_snapshots.id", ondelete="SET NULL"), nullable=True
    )
```

- [ ] **Step 3: Créer `backend/app/models/audit_log.py`**

```python
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, Enum, ForeignKey, Index, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.enums import AuditResult
from app.models.mixins import UUIDPrimaryKeyMixin


class AuditLog(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "audit_log"
    __table_args__ = (Index("ix_audit_log_user_created", "user_id", "created_at"),)

    user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    google_connection_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("google_connections.id", ondelete="SET NULL"), nullable=True
    )
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    resource_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    resource_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    request_payload_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    result: Mapped[AuditResult] = mapped_column(
        Enum(AuditResult, native_enum=False, create_constraint=True, name="audit_result", length=16),
        nullable=False,
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
```

- [ ] **Step 4: Modifier `backend/app/models/__init__.py` (version finale, 7 modèles)**

```python
from app.models.audit_log import AuditLog
from app.models.audit_snapshot import AuditSnapshot
from app.models.google_connection import GoogleConnection
from app.models.issue_item import IssueItem
from app.models.user import User
from app.models.website import Website
from app.models.website_google_link import WebsiteGoogleLink

__all__ = [
    "AuditLog",
    "AuditSnapshot",
    "GoogleConnection",
    "IssueItem",
    "User",
    "Website",
    "WebsiteGoogleLink",
]
```

- [ ] **Step 5: Écrire les tests qui échouent — `backend/tests/test_models_journal.py`**

```python
from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_log import AuditLog
from app.models.audit_snapshot import AuditSnapshot
from app.models.enums import (
    AuditResult,
    IssueCategory,
    IssueSeverity,
    IssueStatus,
    SnapshotSource,
)
from app.models.google_connection import GoogleConnection
from app.models.issue_item import IssueItem
from app.models.user import User
from app.models.website import Website


async def _site(session: AsyncSession) -> Website:
    user = User(email="j@example.com", google_sub="sub-j")
    session.add(user)
    await session.flush()
    site = Website(user_id=user.id, domain="j.com", display_name="J")
    session.add(site)
    await session.flush()
    return site


async def test_snapshot_stores_jsonb_metrics(db_session: AsyncSession) -> None:
    site = await _site(db_session)
    snap = AuditSnapshot(
        website_id=site.id,
        captured_at=datetime.now(UTC),
        source=SnapshotSource.PAGESPEED,
        metrics={"performance": 0.82, "lcp_ms": 2400},
    )
    db_session.add(snap)
    await db_session.flush()
    await db_session.refresh(snap)
    assert snap.metrics["lcp_ms"] == 2400


async def test_issue_status_defaults_todo(db_session: AsyncSession) -> None:
    site = await _site(db_session)
    issue = IssueItem(
        website_id=site.id,
        title="Balise title manquante",
        description="…",
        category=IssueCategory.SEO,
        severity=IssueSeverity.MEDIUM,
        fingerprint="seo:missing-title:/",
        detected_at=datetime.now(UTC),
    )
    db_session.add(issue)
    await db_session.flush()
    assert issue.status == IssueStatus.TODO


async def test_issue_unique_fingerprint_per_site(db_session: AsyncSession) -> None:
    site = await _site(db_session)
    common = {
        "website_id": site.id,
        "title": "x",
        "description": "x",
        "category": IssueCategory.SEO,
        "severity": IssueSeverity.LOW,
        "fingerprint": "dup",
        "detected_at": datetime.now(UTC),
    }
    db_session.add(IssueItem(**common))
    await db_session.flush()
    db_session.add(IssueItem(**common))
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_snapshot_delete_nulls_issue_link(db_session: AsyncSession) -> None:
    site = await _site(db_session)
    snap = AuditSnapshot(
        website_id=site.id,
        captured_at=datetime.now(UTC),
        source=SnapshotSource.GA4,
        metrics={},
    )
    db_session.add(snap)
    await db_session.flush()
    issue = IssueItem(
        website_id=site.id,
        title="x",
        description="x",
        category=IssueCategory.ANALYTICS,
        severity=IssueSeverity.LOW,
        fingerprint="fp",
        detected_at=datetime.now(UTC),
        source_snapshot_id=snap.id,
    )
    db_session.add(issue)
    await db_session.flush()
    await db_session.delete(snap)
    await db_session.flush()
    await db_session.refresh(issue)
    assert issue.source_snapshot_id is None


async def test_audit_log_survives_user_delete(db_session: AsyncSession) -> None:
    user = User(email="a@example.com", google_sub="sub-a")
    db_session.add(user)
    await db_session.flush()
    log = AuditLog(
        user_id=user.id,
        action="google_connection.created",
        result=AuditResult.SUCCESS,
    )
    db_session.add(log)
    await db_session.flush()
    await db_session.delete(user)
    await db_session.flush()
    rows = (await db_session.execute(select(AuditLog))).scalars().all()
    assert len(rows) == 1
    assert rows[0].user_id is None
```

- [ ] **Step 6: Lancer — attendu : PASS**

Run: `cd backend && uv run pytest tests/test_models_journal.py -v`
Expected: 5 tests PASSED.

- [ ] **Step 7: Lancer toute la suite modèles + santé**

Run: `cd backend && uv run pytest -v`
Expected: tous verts (santé + 3 fichiers modèles).

- [ ] **Step 8: Lint + commit**

```bash
cd backend && uv run ruff check .
git add backend/app/models backend/tests/test_models_journal.py
git commit -m "feat(models): AuditSnapshot, IssueItem, AuditLog"
```

---

## Task 7: Alembic — configuration async + migration initiale

**Files:**
- Create: `backend/alembic.ini`
- Create: `backend/alembic/env.py`
- Create: `backend/alembic/script.py.mako`
- Create: `backend/alembic/versions/` (dossier, via `alembic init`)
- Create: `backend/alembic/versions/<hash>_initial_schema.py` (autogénérée puis relue)
- Create: `backend/tests/test_migrations.py`

**Interfaces:**
- Consumes: `app.db.base.Base`, `app.models` (métadonnées complètes — T4–T6), `app.config.get_settings`.
- Produces :
  - `alembic upgrade head` crée les 7 tables sur la base ciblée par `ALEMBIC_DATABASE_URL` (sinon `settings.database_url`).
  - `alembic downgrade base` supprime tout proprement.
  - `alembic check` ne détecte aucune divergence modèles ⇔ migration.

- [ ] **Step 1: Scaffolder Alembic**

Run: `cd backend && uv run alembic init -t async alembic`
Expected: crée `alembic.ini`, `alembic/env.py`, `alembic/script.py.mako`, `alembic/versions/`.

- [ ] **Step 2: Nettoyer `alembic.ini`**

Dans `alembic.ini`, laisser `sqlalchemy.url` **vide** (l'URL vient de `env.py`) :
```ini
sqlalchemy.url =
```
Régler `script_location = alembic` et `prepend_sys_path = .` (déjà par défaut).

- [ ] **Step 3: Remplacer `backend/alembic/env.py`**

```python
import asyncio
import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy.ext.asyncio import async_engine_from_config
from sqlalchemy import pool

from app.config import get_settings
from app.db.base import Base
import app.models  # noqa: F401 — peuple Base.metadata

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _database_url() -> str:
    return os.environ.get("ALEMBIC_DATABASE_URL") or get_settings().database_url


def run_migrations_offline() -> None:
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=False,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=False,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = _database_url()
    connectable = async_engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
```

> `compare_server_default=False` est délibéré : avec `True`, `alembic check`
> signale de faux écarts sur les `server_default=func.now()` (Postgres renvoie
> `now()` sous une forme normalisée qu'Alembic ne reconnaît pas comme
> identique). `compare_type=True` reste actif. Les changements de schéma passent
> de toute façon par des migrations explicites, jamais par autogenerate seul.

- [ ] **Step 4: Générer la migration initiale**

Run:
```bash
cd backend && ALEMBIC_DATABASE_URL="postgresql+asyncpg://cc:cc@localhost:55432/control_center_migrations" uv run alembic revision --autogenerate -m "initial schema"
```
Expected: un fichier `alembic/versions/<hash>_initial_schema.py` apparaît.

- [ ] **Step 5: Relire la migration à la main**

Ouvrir le fichier généré. Vérifier :
- `op.create_table("users", …)` … pour les **7** tables : `users`, `google_connections`, `websites`, `website_google_links`, `audit_snapshots`, `issue_items`, `audit_log`.
- Les FKs portent `ondelete="CASCADE"` ou `"SET NULL"` conformes à la spec §3.
- Les `CheckConstraint` des enums (`native_enum=False`) sont présents et nommés `ck_<table>_<enum_name>`.
- Les `UniqueConstraint` : `uq_google_connections_user_google_sub`… en fait nommés d'après `name=` fourni → `uq_...`? Avec la naming convention `uq`, le nom devient `uq_<table>_<col0>` **sauf** si `name=` explicite est donné, auquel cas Alembic utilise `name`. Vérifier simplement que 4 contraintes uniques existent : `google_connections(user_id, google_sub)`, `websites(user_id, domain)`, `website_google_links(website_id, resource_type, resource_id)`, `issue_items(website_id, fingerprint)`.
- Les `Index` `ix_audit_snapshots_website_captured` et `ix_audit_log_user_created`.
- `downgrade()` fait bien le `op.drop_table` de toutes les tables dans l'ordre inverse.

Corriger l'ordre des `create_table`/`drop_table` si une FK est créée avant sa table cible (rare avec l'autogénération, mais à vérifier).

- [ ] **Step 6: Appliquer puis annuler la migration manuellement**

```bash
cd backend
export ALEMBIC_DATABASE_URL="postgresql+asyncpg://cc:cc@localhost:55432/control_center_migrations"
uv run alembic upgrade head
uv run alembic downgrade base
uv run alembic upgrade head
```
Expected: aucune erreur sur les 3 commandes.

- [ ] **Step 7: Vérifier la synchro modèles ⇔ migration**

Run: `cd backend && ALEMBIC_DATABASE_URL="postgresql+asyncpg://cc:cc@localhost:55432/control_center_migrations" uv run alembic check`
Expected: `No new upgrade operations detected.`
Si des opérations sont détectées : la migration ne reflète pas les modèles → régénérer ou corriger à la main, puis relancer `alembic check`.

- [ ] **Step 8: Écrire le test — `backend/tests/test_migrations.py`**

```python
import os
import subprocess
import sys
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import get_settings

BACKEND_DIR = Path(__file__).resolve().parents[1]
MIG_URL = get_settings().database_url_migrations_test
EXPECTED_TABLES = {
    "users",
    "google_connections",
    "websites",
    "website_google_links",
    "audit_snapshots",
    "issue_items",
    "audit_log",
}


def _alembic(*args: str) -> subprocess.CompletedProcess:
    # `python -m alembic` via l'interpréteur courant : sous `python -m uv run
    # pytest`, sys.executable est le python du venv (alembic y est installé).
    # On n'appelle pas `uv` en sous-processus car uv n'est pas sur le PATH.
    env = {**os.environ, "ALEMBIC_DATABASE_URL": MIG_URL}
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=BACKEND_DIR,
        env=env,
        capture_output=True,
        text=True,
    )


async def _table_names() -> set[str]:
    engine = create_async_engine(MIG_URL)
    try:
        async with engine.connect() as conn:
            names = await conn.run_sync(lambda c: set(inspect(c).get_table_names()))
        return names
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def clean_migrations_db():
    _alembic("downgrade", "base")
    yield
    _alembic("downgrade", "base")


async def test_upgrade_creates_all_tables(clean_migrations_db) -> None:
    result = _alembic("upgrade", "head")
    assert result.returncode == 0, result.stderr
    names = await _table_names()
    assert EXPECTED_TABLES.issubset(names)


async def test_downgrade_drops_all_tables(clean_migrations_db) -> None:
    assert _alembic("upgrade", "head").returncode == 0
    assert _alembic("downgrade", "base").returncode == 0
    names = await _table_names()
    assert EXPECTED_TABLES.isdisjoint(names)


async def test_models_match_migration(clean_migrations_db) -> None:
    assert _alembic("upgrade", "head").returncode == 0
    check = _alembic("check")
    assert check.returncode == 0, f"schéma désynchronisé:\n{check.stdout}\n{check.stderr}"
```

- [ ] **Step 9: Lancer — attendu : PASS**

Run: `cd backend && python -m uv run pytest tests/test_migrations.py -v`
Expected: 3 tests PASSED. (Ces tests lancent `alembic` en sous-processus ; ils sont plus lents — ~5-10 s.)

- [ ] **Step 10: Appliquer la migration à la base de dev**

Run: `cd backend && python -m uv run alembic upgrade head`
(cible `control_center` via `settings.database_url`)
Expected: `Running upgrade  -> <hash>, initial schema`.

- [ ] **Step 11: Lint + commit**

```bash
cd backend && uv run ruff check .
git add backend/alembic.ini backend/alembic backend/tests/test_migrations.py
git commit -m "feat(db): alembic async config + initial schema migration"
```

---

## Task 8: Module de chiffrement des refresh tokens Google

**Files:**
- Create: `backend/app/security/__init__.py` (vide)
- Create: `backend/app/security/token_crypto.py`
- Create: `backend/tests/test_token_crypto.py`

**Interfaces:**
- Consumes: `app.config.Settings` (champs `token_enc_keys: dict[int, str]`, `token_enc_active_version: int` — T2).
- Produces :
  - `EncryptedToken` — dataclass frozen : `ciphertext: bytes`, `nonce: bytes`, `key_version: int`. Méthodes : `.pack() -> bytes`, classmethod `.unpack(blob: bytes) -> EncryptedToken`.
  - `TokenCipher(keys: dict[int, bytes], active_version: int)` :
    - `.encrypt(plaintext: str, *, aad: bytes | None = None) -> EncryptedToken`
    - `.decrypt(token: EncryptedToken, *, aad: bytes | None = None) -> str`
    - `.rotate(token: EncryptedToken, *, aad: bytes | None = None) -> EncryptedToken`
  - `load_token_cipher(settings: Settings) -> TokenCipher`
  - Exceptions : `TokenCryptoError` (base), `TokenDecryptionError`, `UnknownKeyVersionError`, `TokenCryptoConfigError`.

- [ ] **Step 1: Créer `backend/app/security/__init__.py`** (vide)

- [ ] **Step 2: Écrire les tests qui échouent — `backend/tests/test_token_crypto.py`**

```python
import base64
import os

import pytest

from app.security.token_crypto import (
    EncryptedToken,
    TokenCipher,
    TokenCryptoConfigError,
    TokenDecryptionError,
    UnknownKeyVersionError,
    load_token_cipher,
)

KEY_V1 = os.urandom(32)
KEY_V2 = os.urandom(32)


def cipher(active: int = 1) -> TokenCipher:
    return TokenCipher(keys={1: KEY_V1, 2: KEY_V2}, active_version=active)


def test_round_trip() -> None:
    c = cipher()
    token = c.encrypt("1//refresh-token-secret")
    assert isinstance(token, EncryptedToken)
    assert token.key_version == 1
    assert c.decrypt(token) == "1//refresh-token-secret"


def test_encrypt_uses_active_version() -> None:
    token = cipher(active=2).encrypt("x")
    assert token.key_version == 2


def test_pack_unpack_survives_round_trip() -> None:
    c = cipher()
    token = c.encrypt("secret-value")
    blob = token.pack()
    restored = EncryptedToken.unpack(blob)
    assert restored == token
    assert c.decrypt(restored) == "secret-value"


def test_nonce_is_unique_per_encryption() -> None:
    c = cipher()
    nonces = {c.encrypt("same").nonce for _ in range(50)}
    assert len(nonces) == 50


def test_tampered_ciphertext_raises() -> None:
    c = cipher()
    token = c.encrypt("secret")
    tampered = EncryptedToken(
        ciphertext=bytes([token.ciphertext[0] ^ 0x01]) + token.ciphertext[1:],
        nonce=token.nonce,
        key_version=token.key_version,
    )
    with pytest.raises(TokenDecryptionError):
        c.decrypt(tampered)


def test_aad_mismatch_raises() -> None:
    c = cipher()
    token = c.encrypt("secret", aad=b"user-123")
    with pytest.raises(TokenDecryptionError):
        c.decrypt(token, aad=b"user-999")
    assert c.decrypt(token, aad=b"user-123") == "secret"


def test_unknown_key_version_raises() -> None:
    c = cipher()
    token = EncryptedToken(ciphertext=b"x" * 20, nonce=b"y" * 12, key_version=99)
    with pytest.raises(UnknownKeyVersionError):
        c.decrypt(token)


def test_rotate_reencrypts_to_active_version() -> None:
    old = TokenCipher(keys={1: KEY_V1, 2: KEY_V2}, active_version=1)
    token_v1 = old.encrypt("secret")
    new = TokenCipher(keys={1: KEY_V1, 2: KEY_V2}, active_version=2)
    token_v2 = new.rotate(token_v1)
    assert token_v2.key_version == 2
    assert new.decrypt(token_v2) == "secret"
    # l'ancien token reste déchiffrable tant que la clé v1 est dans le registre
    assert new.decrypt(token_v1) == "secret"


def test_load_from_settings(monkeypatch) -> None:
    class FakeSettings:
        token_enc_keys = {
            1: base64.b64encode(KEY_V1).decode(),
            2: base64.b64encode(KEY_V2).decode(),
        }
        token_enc_active_version = 2

    c = load_token_cipher(FakeSettings())
    assert c.decrypt(c.encrypt("hello")) == "hello"


def test_load_rejects_short_key() -> None:
    class FakeSettings:
        token_enc_keys = {1: base64.b64encode(b"tooshort").decode()}
        token_enc_active_version = 1

    with pytest.raises(TokenCryptoConfigError):
        load_token_cipher(FakeSettings())


def test_load_rejects_missing_active_version() -> None:
    class FakeSettings:
        token_enc_keys = {1: base64.b64encode(KEY_V1).decode()}
        token_enc_active_version = 5

    with pytest.raises(TokenCryptoConfigError):
        load_token_cipher(FakeSettings())
```

- [ ] **Step 3: Lancer — attendu : FAIL (import manquant)**

Run: `cd backend && uv run pytest tests/test_token_crypto.py -v`
Expected: `ModuleNotFoundError: No module named 'app.security.token_crypto'`.

- [ ] **Step 4: Créer `backend/app/security/token_crypto.py`**

```python
from __future__ import annotations

import base64
import os
from dataclasses import dataclass

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

_VERSION_BYTES = 2
_NONCE_BYTES = 12
_KEY_BYTES = 32
_BYTE_ORDER = "big"


class TokenCryptoError(Exception):
    """Base de toutes les erreurs de ce module."""


class TokenDecryptionError(TokenCryptoError):
    """Authentification GCM échouée : blob corrompu, mauvaise clé, ou AAD incorrecte."""


class UnknownKeyVersionError(TokenCryptoError):
    """La version de clé du token n'est pas dans le registre."""


class TokenCryptoConfigError(TokenCryptoError):
    """Configuration d'environnement invalide."""


@dataclass(frozen=True)
class EncryptedToken:
    ciphertext: bytes
    nonce: bytes
    key_version: int

    def pack(self) -> bytes:
        return (
            self.key_version.to_bytes(_VERSION_BYTES, _BYTE_ORDER)
            + self.nonce
            + self.ciphertext
        )

    @classmethod
    def unpack(cls, blob: bytes) -> EncryptedToken:
        if len(blob) < _VERSION_BYTES + _NONCE_BYTES:
            raise TokenDecryptionError("blob trop court")
        version = int.from_bytes(blob[:_VERSION_BYTES], _BYTE_ORDER)
        nonce = blob[_VERSION_BYTES : _VERSION_BYTES + _NONCE_BYTES]
        ciphertext = blob[_VERSION_BYTES + _NONCE_BYTES :]
        return cls(ciphertext=ciphertext, nonce=nonce, key_version=version)


class TokenCipher:
    def __init__(self, keys: dict[int, bytes], active_version: int) -> None:
        if active_version not in keys:
            raise TokenCryptoConfigError(
                f"version active {active_version} absente du registre de clés"
            )
        for version, key in keys.items():
            if len(key) != _KEY_BYTES:
                raise TokenCryptoConfigError(
                    f"la clé v{version} fait {len(key)} octets, {_KEY_BYTES} attendus"
                )
        self._keys = dict(keys)
        self._active_version = active_version

    def _aesgcm(self, version: int) -> AESGCM:
        try:
            return AESGCM(self._keys[version])
        except KeyError as exc:
            raise UnknownKeyVersionError(f"version de clé inconnue : {version}") from exc

    def encrypt(self, plaintext: str, *, aad: bytes | None = None) -> EncryptedToken:
        nonce = os.urandom(_NONCE_BYTES)
        ciphertext = self._aesgcm(self._active_version).encrypt(
            nonce, plaintext.encode("utf-8"), aad
        )
        return EncryptedToken(
            ciphertext=ciphertext, nonce=nonce, key_version=self._active_version
        )

    def decrypt(self, token: EncryptedToken, *, aad: bytes | None = None) -> str:
        aesgcm = self._aesgcm(token.key_version)
        try:
            plaintext = aesgcm.decrypt(token.nonce, token.ciphertext, aad)
        except InvalidTag as exc:
            raise TokenDecryptionError(
                "échec d'authentification du token chiffré"
            ) from exc
        return plaintext.decode("utf-8")

    def rotate(
        self, token: EncryptedToken, *, aad: bytes | None = None
    ) -> EncryptedToken:
        plaintext = self.decrypt(token, aad=aad)
        return self.encrypt(plaintext, aad=aad)


def load_token_cipher(settings: object) -> TokenCipher:
    raw_keys: dict[int, str] = getattr(settings, "token_enc_keys")
    active_version: int = getattr(settings, "token_enc_active_version")
    decoded: dict[int, bytes] = {}
    for version, b64 in raw_keys.items():
        try:
            decoded[int(version)] = base64.b64decode(b64, validate=True)
        except (ValueError, TypeError) as exc:
            raise TokenCryptoConfigError(
                f"clé v{version} : base64 invalide"
            ) from exc
    return TokenCipher(keys=decoded, active_version=active_version)
```

- [ ] **Step 5: Lancer — attendu : PASS**

Run: `cd backend && uv run pytest tests/test_token_crypto.py -v`
Expected: 11 tests PASSED.

- [ ] **Step 6: Lancer toute la suite**

Run: `cd backend && uv run pytest -v`
Expected: tous les tests verts (santé, modèles, migrations, crypto).

- [ ] **Step 7: Lint + commit**

```bash
cd backend && uv run ruff check .
git add backend/app/security backend/tests/test_token_crypto.py
git commit -m "feat(security): AES-256-GCM refresh token cipher with key versioning"
```

---

## Task 9: Frontend — squelette Next.js + page santé

**Files:**
- Create: `frontend/` (via `create-next-app`)
- Create: `frontend/.env.example`
- Create: `frontend/lib/api.ts`
- Modify: `frontend/app/page.tsx`
- Create: `frontend/app/health/page.tsx`

**Interfaces:**
- Consumes: `GET {NEXT_PUBLIC_API_BASE_URL}/health` du backend (T2).
- Produces : app Next.js qui build (`npm run build`) et affiche l'état du backend sur `/health`.

- [ ] **Step 1: Scaffolder Next.js**

Run (depuis la racine `Guiili/`) :
```bash
npx --yes create-next-app@latest frontend --typescript --app --eslint --no-tailwind --no-src-dir --no-turbopack --import-alias "@/*" --use-npm
```
Expected: `frontend/` créé avec App Router + TypeScript, sans prompt interactif
(tous les choix sont passés en flags ; `--yes` évite la question d'installation
de `create-next-app`).

> Si `create-next-app` refuse à cause d'un `.gitignore`/`README.md` déjà présents
> à la racine : ce n'est pas le cas, il écrit dans `frontend/` qui est vide.
> Si une version future retire un flag, garder les valeurs équivalentes
> (TypeScript oui, App Router oui, Tailwind non, src/ non, alias `@/*`).

- [ ] **Step 2: Créer `frontend/.env.example`**

```
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
```
Puis : `cd frontend && cp .env.example .env.local`

- [ ] **Step 3: Créer `frontend/lib/api.ts`**

```typescript
const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export type HealthResponse = { status: string };

export async function getBackendHealth(): Promise<HealthResponse> {
  const res = await fetch(`${API_BASE_URL}/health`, { cache: "no-store" });
  if (!res.ok) {
    throw new Error(`Backend health check failed: ${res.status}`);
  }
  return res.json() as Promise<HealthResponse>;
}
```

- [ ] **Step 4: Remplacer `frontend/app/page.tsx`**

```tsx
export default function Home() {
  return (
    <main style={{ padding: 32, fontFamily: "system-ui, sans-serif" }}>
      <h1>Control Center Marketing Agentique</h1>
      <p>
        Squelette. Voir <a href="/health">/health</a> pour l&apos;état du backend.
      </p>
    </main>
  );
}
```

- [ ] **Step 5: Créer `frontend/app/health/page.tsx`**

```tsx
import { getBackendHealth } from "@/lib/api";

export default async function HealthPage() {
  let status: string;
  try {
    const health = await getBackendHealth();
    status = health.status;
  } catch (err) {
    status = `unreachable (${(err as Error).message})`;
  }

  return (
    <main style={{ padding: 32, fontFamily: "system-ui, sans-serif" }}>
      <h1>Backend health</h1>
      <p>
        Status: <strong>{status}</strong>
      </p>
    </main>
  );
}
```

- [ ] **Step 6: Vérifier le lint et le build**

Run: `cd frontend && npm run lint && npm run build`
Expected: lint sans erreur, build réussi (`/` et `/health` compilées).

- [ ] **Step 7: Vérification manuelle end-to-end (optionnelle mais recommandée)**

Avec `docker compose up -d` et le backend lancé (`cd backend && uv run uvicorn app.main:app`) :
```bash
cd frontend && npm run dev
```
Ouvrir `http://localhost:3000/health` → doit afficher `Status: ok`.
Arrêter le backend, rafraîchir → `Status: unreachable (...)`.

- [ ] **Step 8: Commit**

```bash
git add frontend/
git commit -m "feat(frontend): Next.js skeleton with backend health page"
```

---

## Self-Review

**1. Couverture de la spec**

| Élément de spec | Tâche(s) |
|---|---|
| §1 objectif : monorepo backend/frontend | T1, T2, T9 |
| §1 : infra Docker (PG16 + Redis7) | T1 |
| §1 : `/health` + `/health/db` | T2, T3 |
| §2 : uv, Python 3.12 | T2 |
| §2 : SQLAlchemy 2.0 async / asyncpg | T3 |
| §2 : naming convention MetaData | T3 (base.py) |
| §2 : Alembic uniquement, create_all réservé aux tests | T3 (fixtures), T7 |
| §3.1 `users` | T4 |
| §3.2 `google_connections` (+ unique user/google_sub) | T4 |
| §3.3 `websites` (+ unique user/domain) | T5 |
| §3.4 `website_google_links` (+ unique triplet) | T5 |
| §3.5 `audit_snapshots` (JSONB, index) | T6 |
| §3.6 `issue_items` (+ unique fingerprint, FK SET NULL) | T6 |
| §3.7 `audit_log` (FKs SET NULL, index) | T6 |
| §3 : enums en VARCHAR+CHECK | T4 (enums.py), utilisés T4–T6, testé T5/T6 |
| §3 : migration initiale + `alembic check` propre | T7 |
| §4 : module AES-256-GCM | T8 |
| §4.2 : format pack/unpack versionné | T8 (testé) |
| §4.3 : registre de clés + rotation | T8 (testé) |
| §4.4 : erreurs jamais silencieuses | T8 (exceptions dédiées, testées) |
| §5 : structure monorepo | T1–T9 (conforme à l'arbre) |
| §6 : `.env.example` backend + frontend | T2, T9 |
| §7 hors périmètre (OAuth, sessions, agent) | non implémenté — conforme |

Aucun trou identifié.

**2. Placeholders**

- T7 Step 8 contient un squelette de test **délibérément cassé**, immédiatement remplacé par la version correcte au Step 9 (motif pédagogique explicite, pas un placeholder oublié). Acceptable car le code final complet est fourni.
- Aucun « TODO », « à compléter », « gérer les cas limites » sans code.

**3. Cohérence des types**

- `EncryptedToken(ciphertext, nonce, key_version)` : signature identique dans le module (T8 Step 4) et les tests (T8 Step 2).
- `TokenCipher.encrypt/decrypt/rotate` : mêmes signatures partout (`*, aad: bytes | None = None`).
- `get_session` : défini dans `app.db.session` (T3), overridé dans `conftest.py` (T3), consommé par `main.py` (T3). Cohérent.
- `build_engine(url: str)` : défini T3, utilisé dans `conftest.py` (T3). Cohérent.
- Enums (`ConnectionStatus`, `ResourceType`, `SnapshotSource`, `IssueCategory`, `IssueSeverity`, `IssueStatus`, `AuditResult`) : définis une fois en T4, importés tels quels en T4–T6 et dans les tests.
- `ALEMBIC_DATABASE_URL` : lu dans `env.py` (T7 Step 3), positionné par la commande T7 Step 4/6 et par `test_migrations.py` (T7 Step 9). Cohérent.
- Noms des 7 tables : identiques entre spec §3, modèles T4–T6, `EXPECTED_TABLES` de `test_migrations.py`, et checklist T7 Step 5.

**4. Points d'attention pour l'exécutant**

- L'ordre T3 → T4 crée une dépendance circulaire apparente : `conftest.py` (T3) importe `app.models`. T3 Step 6 crée donc un `app/models/__init__.py` vide, complété ensuite. Ne pas sauter cette étape.
- `app/models/__init__.py` évolue en T4 (2 modèles), T5 (+2), T6 (+3). La version finale à 7 entrées est celle qui doit rester.
- Les tests de T7 lancent `uv run alembic` en sous-processus : ils nécessitent que `docker compose` tourne et que la base `control_center_migrations` existe (T1 Step 6).
