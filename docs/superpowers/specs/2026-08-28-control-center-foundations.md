# Spec — Control Center Marketing Agentique : Fondations techniques (P0)

**Statut :** actif
**Date :** 2026-08-28
**Phase roadmap :** P0 — Fondations (voir [plan-v3.md](../../reference/plan-v3.md) §2)
**Portée de cette spec :** initialisation de l'environnement technique uniquement.
Pas d'OAuth Google fonctionnel, pas d'agent Claude, pas d'UI produit — ces
briques sont des specs distinctes (P0 suite, puis P1).

---

## 1. Objectif

Poser un monorepo `backend/` (FastAPI + SQLAlchemy 2.0 async + Alembic) et
`frontend/` (Next.js) avec :

1. une infra locale reproductible (Docker Compose : PostgreSQL 16 + Redis 7) ;
2. les 7 tables du modèle de données MVP, versionnées par une migration Alembic
   initiale, avec `alembic check` propre (modèles ⇔ migration synchronisés) ;
3. un module de chiffrement symétrique AES-256-GCM pour les refresh tokens
   Google, avec gestion de version de clé et rotation ;
4. un endpoint `/health` + `/health/db` prouvant que l'app démarre et parle à
   Postgres ;
5. un squelette Next.js qui build et appelle `/health`.

**Critère de "fait" :** `docker compose up -d` puis, côté backend,
`uv run alembic upgrade head && uv run pytest` tout vert ; côté frontend,
`npm run build` OK.

---

## 2. Contraintes projet (verbatim — s'appliquent à toutes les tâches)

- **Développeur solo, temps partiel.** Préférer la simplicité : pas
  d'abstraction spéculative, pas de couche non utilisée dans cette spec.
- **Python** géré par `uv`. `pyproject.toml` + `uv.lock` commités.
  Cible : **Python 3.12**.
- **SQLAlchemy 2.0**, style `Mapped[]` / `mapped_column()`, moteur **async**
  (`asyncpg`).
- **Node : version 20 LTS ou supérieure.** Frontend en **TypeScript**, gestionnaire
  de paquets **npm**, Next.js **App Router**.
- **Scopes Google du MVP, en dur nulle part ailleurs que la config :**
  `openid`, `email`, `profile`, `https://www.googleapis.com/auth/analytics.readonly`,
  `https://www.googleapis.com/auth/webmasters.readonly`. Lecture seule. Aucune
  écriture GTM/GA4.
- **Auth applicative : Google OIDC uniquement.** `users.auth_provider` vaut
  toujours `'google'` dans cette phase ; `users.google_sub` (subject OIDC) est la
  clé d'identité. Aucun mot de passe stocké.
- **Refresh tokens Google : jamais en clair.** Chiffrés AES-256-GCM au repos.
  Les access tokens ne sont **jamais** persistés en base.
- **Zéro secret commité.** `.env` est gitignore ; `.env.example` documente chaque
  variable sans valeur réelle.
- **Migrations Alembic uniquement** pour tout changement de schéma. Pas de
  `create_all()` en code applicatif (autorisé seulement dans les fixtures de test).
- **Nommage des contraintes déterministe** via une `MetaData` naming convention
  (sinon les migrations autogénérées sont instables).

---

## 3. Modèle de données

7 tables. IDs = **UUID v4** (`sqlalchemy.Uuid`, natif Postgres `UUID`), générés
côté Python (`default=uuid4`). Tous les timestamps sont `TIMESTAMP WITH TIME ZONE`
(`DateTime(timezone=True)`), `created_at`/`updated_at` avec
`server_default=func.now()` et `onupdate=func.now()` pour `updated_at`.

Les colonnes "énumérées" utilisent `sa.Enum(PyEnum, native_enum=False, create_constraint=True)` →
colonne `VARCHAR` + `CHECK`, pour éviter la douleur des `ALTER TYPE` Postgres.

### 3.1 `users`

| colonne | type | contraintes |
|---|---|---|
| `id` | UUID | PK |
| `email` | str(320) | NOT NULL, UNIQUE |
| `auth_provider` | str(32) | NOT NULL, default `'google'` |
| `google_sub` | str(255) | NOT NULL, UNIQUE — subject OIDC du compte de login |
| `display_name` | str(255) | NULL |
| `created_at` | timestamptz | NOT NULL, server_default now() |
| `updated_at` | timestamptz | NOT NULL, server_default now(), onupdate now() |

### 3.2 `google_connections`

Une ligne = une identité Google liée par un utilisateur. Un utilisateur a N lignes.

| colonne | type | contraintes |
|---|---|---|
| `id` | UUID | PK |
| `user_id` | UUID | FK → `users.id` ON DELETE CASCADE, NOT NULL |
| `google_account_email` | str(320) | NOT NULL |
| `google_sub` | str(255) | NOT NULL — subject de l'identité connectée (peut différer du login) |
| `granted_scopes` | ARRAY(str) | NOT NULL — scopes **réellement accordés** |
| `refresh_token_encrypted` | LargeBinary | NOT NULL — blob packé (voir §4) |
| `encryption_key_version` | int | NOT NULL — dénormalisé pour cibler les lignes lors d'une rotation |
| `status` | enum(`active`,`needs_reauth`,`revoked`) | NOT NULL, default `active` |
| `created_at` | timestamptz | NOT NULL, server_default now() |
| `updated_at` | timestamptz | NOT NULL, server_default now(), onupdate now() |
| `last_refreshed_at` | timestamptz | NULL |

Contrainte : `UNIQUE (user_id, google_sub)` — un utilisateur ne lie pas deux fois
la même identité Google.

### 3.3 `websites`

| colonne | type | contraintes |
|---|---|---|
| `id` | UUID | PK |
| `user_id` | UUID | FK → `users.id` ON DELETE CASCADE, NOT NULL |
| `domain` | str(255) | NOT NULL |
| `display_name` | str(255) | NOT NULL |
| `created_at` | timestamptz | NOT NULL, server_default now() |
| `updated_at` | timestamptz | NOT NULL, server_default now(), onupdate now() |

Contrainte : `UNIQUE (user_id, domain)`.

### 3.4 `website_google_links`

Table de jointure : quelle ressource Google (venant de quelle connexion) sert
quel site interne. C'est ce qui permet `monsite.com` → GA4 de la connexion A +
GTM de la connexion B + GSC de la connexion C.

| colonne | type | contraintes |
|---|---|---|
| `id` | UUID | PK |
| `website_id` | UUID | FK → `websites.id` ON DELETE CASCADE, NOT NULL |
| `google_connection_id` | UUID | FK → `google_connections.id` ON DELETE CASCADE, NOT NULL |
| `resource_type` | enum(`ga4_property`,`gtm_container`,`gsc_site`) | NOT NULL |
| `resource_id` | str(255) | NOT NULL — ex. `properties/123456789`, `GTM-XXXXXX`, `sc-domain:example.com` |
| `resource_display_name` | str(255) | NULL |
| `linked_at` | timestamptz | NOT NULL, server_default now() |

Contrainte : `UNIQUE (website_id, resource_type, resource_id)`.

### 3.5 `audit_snapshots`

Capture périodique de scores pour un site (base du "journal de bord" et de la
détection d'anomalie en P2).

| colonne | type | contraintes |
|---|---|---|
| `id` | UUID | PK |
| `website_id` | UUID | FK → `websites.id` ON DELETE CASCADE, NOT NULL |
| `captured_at` | timestamptz | NOT NULL — instant logique de la mesure |
| `source` | enum(`pagespeed`,`ga4`,`gsc`,`composite`) | NOT NULL |
| `metrics` | JSONB | NOT NULL — sac de métriques, ex. `{"performance":0.82,"lcp_ms":2400}` |
| `created_at` | timestamptz | NOT NULL, server_default now() |

Index : `(website_id, captured_at)`.

### 3.6 `issue_items`

Backlog de correctifs avec statut.

| colonne | type | contraintes |
|---|---|---|
| `id` | UUID | PK |
| `website_id` | UUID | FK → `websites.id` ON DELETE CASCADE, NOT NULL |
| `title` | str(255) | NOT NULL |
| `description` | text | NOT NULL |
| `category` | enum(`seo`,`analytics`,`cwv`,`tracking`,`other`) | NOT NULL |
| `severity` | enum(`low`,`medium`,`high`,`critical`) | NOT NULL |
| `status` | enum(`todo`,`in_progress`,`fixed`,`dismissed`) | NOT NULL, default `todo` |
| `fingerprint` | str(255) | NOT NULL — clé de dédup stable d'une détection à l'autre |
| `detected_at` | timestamptz | NOT NULL |
| `resolved_at` | timestamptz | NULL |
| `source_snapshot_id` | UUID | FK → `audit_snapshots.id` ON DELETE SET NULL, NULL |
| `created_at` | timestamptz | NOT NULL, server_default now() |
| `updated_at` | timestamptz | NOT NULL, server_default now(), onupdate now() |

Contrainte : `UNIQUE (website_id, fingerprint)` — une re-détection met à jour, ne
duplique pas.

### 3.7 `audit_log`

Journal d'activité + sécurité. Conservé même si l'utilisateur est supprimé
(valeur de preuve) → FK en `SET NULL`, colonnes nullables.

| colonne | type | contraintes |
|---|---|---|
| `id` | UUID | PK |
| `user_id` | UUID | FK → `users.id` ON DELETE SET NULL, NULL |
| `google_connection_id` | UUID | FK → `google_connections.id` ON DELETE SET NULL, NULL |
| `action` | str(100) | NOT NULL — ex. `google_connection.created`, `snapshot.captured` |
| `resource_type` | str(50) | NULL |
| `resource_id` | str(255) | NULL |
| `request_payload_hash` | str(64) | NULL — SHA-256 hex |
| `result` | enum(`success`,`error`) | NOT NULL |
| `error_message` | text | NULL |
| `ip_address` | str(45) | NULL |
| `created_at` | timestamptz | NOT NULL, server_default now() |

Index : `(user_id, created_at)`.

---

## 4. Module de chiffrement des refresh tokens

Fichier : `backend/app/security/token_crypto.py`. Aucune dépendance à SQLAlchemy
ou FastAPI — module pur, testable seul.

### 4.1 Primitive

- **AES-256-GCM** via `cryptography.hazmat.primitives.ciphers.aead.AESGCM`.
- Clé : 32 octets. Nonce : 12 octets aléatoires (`os.urandom`) par chiffrement,
  jamais réutilisé.
- **AAD (Additional Authenticated Data) optionnelle** : le module accepte un
  `aad: bytes | None`. L'appelant (couche modèle, dans une spec ultérieure)
  liera le chiffré à l'identité en passant `str(user_id).encode()` — empêche de
  déplacer un chiffré d'une ligne à l'autre.

### 4.2 Format de blob packé

`encrypt()` retourne un `EncryptedToken`. Sa méthode `.pack() -> bytes` produit :

```
[ version : 2 octets, big-endian uint ][ nonce : 12 octets ][ ciphertext+tag : reste ]
```

`EncryptedToken.unpack(blob: bytes) -> EncryptedToken` fait l'inverse. C'est ce
blob qui est stocké dans `google_connections.refresh_token_encrypted`. La colonne
`encryption_key_version` stocke la même version que l'en-tête (dénormalisation
assumée, pour les requêtes de rotation).

### 4.3 Registre de clés & versions

- Clés chargées depuis l'environnement : `TOKEN_ENC_KEYS` = JSON
  `{"1": "<base64 de 32 octets>", "2": "..."}`, et `TOKEN_ENC_ACTIVE_VERSION` = int.
- `TokenCipher(keys: dict[int, bytes], active_version: int)` :
  - `encrypt(plaintext: str, *, aad: bytes | None = None) -> EncryptedToken`
    utilise **toujours** `active_version`.
  - `decrypt(token: EncryptedToken, *, aad: bytes | None = None) -> str` choisit
    la clé d'après `token.key_version`.
  - `rotate(token: EncryptedToken, *, aad: bytes | None = None) -> EncryptedToken`
    déchiffre avec l'ancienne version, re-chiffre avec `active_version` (nouveau
    nonce).
- `load_token_cipher(settings) -> TokenCipher` : construit depuis la config,
  valide (version active présente ; chaque clé fait 32 octets après décodage
  base64) sinon `TokenCryptoConfigError`.

### 4.4 Erreurs (jamais silencieuses)

- `TokenDecryptionError` : échec d'authentification GCM (`InvalidTag`) — blob
  corrompu, mauvaise clé, ou AAD incorrecte.
- `UnknownKeyVersionError` : `token.key_version` absent du registre.
- `TokenCryptoConfigError` : config d'environnement invalide au chargement.

Aucune de ces erreurs n'est rattrapée dans le module. Toute tentative de
déchiffrement qui échoue doit remonter.

---

## 5. Structure du monorepo (cible de fin de spec)

```
Guiili/
├── .gitignore
├── docker-compose.yml
├── README.md
├── docs/
│   ├── reference/
│   │   ├── plan-v3.md
│   │   └── plan-v3-review-notes.md
│   └── superpowers/
│       ├── specs/2026-08-28-control-center-foundations.md
│       └── plans/2026-08-28-control-center-foundations.md
├── docker/
│   └── postgres-init/
│       └── 01-create-databases.sql        # crée control_center, _test, _migrations
├── backend/
│   ├── pyproject.toml
│   ├── uv.lock
│   ├── .env.example
│   ├── alembic.ini
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py                        # FastAPI + /health, /health/db
│   │   ├── config.py                      # pydantic-settings
│   │   ├── db/
│   │   │   ├── __init__.py
│   │   │   ├── base.py                    # DeclarativeBase + naming convention
│   │   │   └── session.py                 # async engine + async_sessionmaker + dep
│   │   ├── models/
│   │   │   ├── __init__.py                # importe tous les modèles (métadonnées Alembic)
│   │   │   ├── mixins.py
│   │   │   ├── enums.py
│   │   │   ├── user.py
│   │   │   ├── google_connection.py
│   │   │   ├── website.py
│   │   │   ├── website_google_link.py
│   │   │   ├── audit_snapshot.py
│   │   │   ├── issue_item.py
│   │   │   └── audit_log.py
│   │   └── security/
│   │       ├── __init__.py
│   │       └── token_crypto.py
│   ├── alembic/
│   │   ├── env.py                         # async, target_metadata = Base.metadata
│   │   ├── script.py.mako
│   │   └── versions/
│   │       └── <hash>_initial_schema.py
│   └── tests/
│       ├── __init__.py
│       ├── conftest.py
│       ├── test_health.py
│       ├── test_db_health.py
│       ├── test_models_users_connections.py
│       ├── test_models_websites_links.py
│       ├── test_models_journal.py
│       ├── test_migrations.py
│       └── test_token_crypto.py
└── frontend/
    ├── package.json
    ├── package-lock.json
    ├── next.config.ts
    ├── tsconfig.json
    ├── .env.example
    ├── .env.local            # gitignore
    ├── app/
    │   ├── layout.tsx
    │   ├── page.tsx
    │   └── health/
    │       └── page.tsx       # affiche le résultat de GET {API}/health
    └── lib/
        └── api.ts
```

---

## 6. Variables d'environnement

### `backend/.env.example`

```
ENVIRONMENT=local
# 5432 / 6379 déjà pris sur la machine de dev → Compose publie sur 55432 / 6380
DATABASE_URL=postgresql+asyncpg://cc:cc@localhost:55432/control_center
DATABASE_URL_TEST=postgresql+asyncpg://cc:cc@localhost:55432/control_center_test
DATABASE_URL_MIGRATIONS_TEST=postgresql+asyncpg://cc:cc@localhost:55432/control_center_migrations
REDIS_URL=redis://localhost:6380/0

# OAuth Google (créés dans Google Cloud Console — client "Web application")
GOOGLE_CLIENT_ID=
GOOGLE_CLIENT_SECRET=
GOOGLE_OAUTH_REDIRECT_URI=http://localhost:8000/auth/google/callback

# Chiffrement des refresh tokens.
# Générer une clé : python -c "import os,base64;print(base64.b64encode(os.urandom(32)).decode())"
TOKEN_ENC_KEYS={"1":"REMPLACER_PAR_UNE_CLE_BASE64_DE_32_OCTETS"}
TOKEN_ENC_ACTIVE_VERSION=1

# Signature des sessions applicatives (cookie / JWT — spec ultérieure)
APP_SECRET_KEY=REMPLACER
```

### `frontend/.env.example`

```
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
```

---

## 7. Hors périmètre de cette spec (specs suivantes)

- Flow OAuth Google complet (endpoints `/auth/google/*`, PKCE, state, échange de
  code, autorisation incrémentale) — spec P0-suite.
- Découverte des ressources Google (`accountSummaries.list`, etc.).
- Sessions applicatives / cookies / middleware d'auth.
- Agent Claude, outils, détection de stack, export GTM — P1.
- CI/CD, déploiement, hébergement.
- Enveloppe de chiffrement DEK-par-ligne (repoussée à P2, cf. review notes §6).

---

## 8. Références

- Roadmap et décisions produit : [plan-v3.md](../../reference/plan-v3.md)
- Angles morts et arbitrages : [plan-v3-review-notes.md](../../reference/plan-v3-review-notes.md)
