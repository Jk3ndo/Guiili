# Comptes, authentification & workspaces — Incrément A Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remplacer le seed dev (`/dev/workspaces`) par un vrai système de comptes — inscription/
connexion par email+mot de passe ou Google OAuth (identité seule), workspaces créés
automatiquement, invitations pour partager un espace avec quelqu'un d'autre.

**Architecture:** Nouvelles tables (`workspaces`, `workspace_members`, `workspace_invitations`,
`password_reset_tokens`) ; `websites`/`google_connections`/`advisor_usage` migrent de `user_id` à
`workspace_id`. Un helper partagé `app/services/workspaces.py` remplace les 4 copies dupliquées
de `_owned_website` et centralise les vérifications d'appartenance. Session cookie HMAC existante
inchangée (agnostique du provider de login). `EmailSender` (ABC + implémentation console) pour
les invitations et les resets de mot de passe — le vrai fournisseur est différé.

**Tech Stack:** FastAPI/SQLAlchemy/Alembic (existant), `argon2-cffi` (nouveau, hash de mot de
passe), Next.js App Router (existant) pour les pages login/register/invitation.

**Spec:** `docs/superpowers/specs/2026-09-12-auth-workspaces-google-connections-design.md`

## Global Constraints

- Une seule méthode de connexion par compte — jamais de fusion silencieuse par email (§2 de la
  spec). Email dupliqué entre providers → erreur explicite, jamais un merge.
- Connexions Google (`google_connections`) restent **hors périmètre de ce plan** : la spec les
  scope au workspace (§2, §7), mais le flow de connexion de données GA4/GSC lui-même est
  l'incrément B, planifié séparément. Ici, on migre seulement la colonne `user_id`→`workspace_id`
  sur `google_connections` pour que le schéma soit prêt — aucun endpoint de ce plan ne crée de
  ligne `GoogleConnection`.
- GitHub OAuth explicitement hors périmètre (phase 2 séparée, décidée en discussion).
- Fournisseur d'email réel hors périmètre — `ConsoleEmailSender` seulement.
- `role`/`status` (workspace_members, workspace_invitations) en `String` simple, pas `pg_enum` —
  valeurs 100% contrôlées par le code (même convention que `AdvisorThread.role`).
- `ruff check app tests` doit rester propre à chaque tâche ; `pytest -W error` scope large à la
  toute fin (Task 13) — les tâches intermédiaires vérifient leur propre périmètre, la suite
  complète n'est pas censée être verte avant Task 3 incluse (Task 1 casse volontairement les
  fixtures existantes, réparées en Task 2).

---

### Task 1: Modèle de données workspace + migration + refactor des vérifications d'appartenance

**Files:**
- Create: `backend/app/models/workspace.py`, `backend/app/models/workspace_member.py`,
  `backend/app/models/workspace_invitation.py`, `backend/app/models/password_reset_token.py`
- Create: `backend/app/services/workspaces.py`
- Modify: `backend/app/models/__init__.py`, `backend/app/models/user.py`,
  `backend/app/models/website.py`, `backend/app/models/google_connection.py`,
  `backend/app/models/advisor.py` (`AdvisorUsage`), `backend/app/models/oauth_state.py`
- Modify: `backend/app/services/connections.py` (`connection_aad`, `upsert_google_connection` —
  renommage de paramètre seulement, la fonction reste non appelée dans ce plan)
- Modify: `backend/app/api/v1/endpoints/audit.py`, `advisor.py`, `gtm.py`, `websites.py`,
  `google.py`, `dev.py` (vérifications d'appartenance)
- Create: `backend/alembic/versions/<rev>_workspaces.py`
- Test: `backend/tests/test_migrations.py`, `backend/tests/test_enum_check_constraints.py`

**Interfaces:**
- Produces: `app/services/workspaces.py::is_member(session, *, workspace_id, user_id) -> bool`,
  `user_workspace_ids(session, user_id) -> list[UUID]`, `owned_website(session, *, website_id,
  user_id) -> Website` (lève `HTTPException(404)` si non trouvé ou non membre — remplace les 4
  copies de `_owned_website`).
- Consumes: rien de nouveau — c'est la fondation des tâches suivantes.

- [ ] **Step 1: Modèles des nouvelles tables**

```python
# app/models/workspace.py
from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    pass


class Workspace(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "workspaces"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    owner_user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
```

```python
# app/models/workspace_member.py
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.mixins import UUIDPrimaryKeyMixin


class WorkspaceMember(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "workspace_members"
    __table_args__ = (
        UniqueConstraint("workspace_id", "user_id", name="uq_workspace_members_workspace_user"),
    )

    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)  # "owner" | "member"
    joined_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
```

```python
# app/models/workspace_invitation.py
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class WorkspaceInvitation(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "workspace_invitations"

    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    invited_email: Mapped[str] = mapped_column(String(320), nullable=False)
    token: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    invited_by_user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="pending", server_default="pending"
    )  # "pending" | "accepted" | "revoked" | "expired"
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
```

```python
# app/models/password_reset_token.py
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.mixins import UUIDPrimaryKeyMixin


class PasswordResetToken(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "password_reset_tokens"

    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    token: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
```

Ajouter les 4 imports/exports dans `app/models/__init__.py` (suivre le pattern existant des
autres modèles — import à effet de bord pour `Base.metadata`).

- [ ] **Step 2: Modifier `users`, `websites`, `google_connections`, `advisor_usage`, `oauth_state`**

`app/models/user.py` : ajouter `password_hash: Mapped[str | None] = mapped_column(String(255),
nullable=True)` ; changer `google_sub: Mapped[str]` en `Mapped[str | None]` avec
`nullable=True` (retirer `nullable=False`).

`app/models/website.py` : remplacer
```python
user_id: Mapped[UUID] = mapped_column(
    ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
)
```
par
```python
workspace_id: Mapped[UUID] = mapped_column(
    ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
)
```
et `UniqueConstraint("user_id", "domain", name="uq_websites_user_domain")` par
`UniqueConstraint("workspace_id", "domain", name="uq_websites_workspace_domain")`. Retirer la
relationship `user: Mapped[User] = relationship(...)` si elle référence `user_id` (vérifier son
existence actuelle et l'adapter/retirer selon ce qui compile).

`app/models/google_connection.py` : même renommage `user_id`→`workspace_id`,
`UniqueConstraint("user_id", "google_sub", ...)` → `UniqueConstraint("workspace_id",
"google_sub", name="uq_google_connections_workspace_google_sub")`.

`app/models/advisor.py::AdvisorUsage` : `user_id` (PK composite avec `day`) → `workspace_id`.

`app/models/oauth_state.py` : ajouter `workspace_id: Mapped[UUID | None] = mapped_column(
ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=True)` en plus du `user_id` existant
(ne pas y toucher) — colonne non utilisée avant l'incrément B, mais faite maintenant pour éviter
une deuxième migration.

`app/services/connections.py` : renommer le paramètre `user_id` en `workspace_id` dans
`connection_aad` et `upsert_google_connection` (et `GoogleConnection.user_id` →
`GoogleConnection.workspace_id` dans la requête `existing`). Cette fonction n'est appelée par
aucun code de ce plan — le renommage est nécessaire seulement pour que le fichier continue de
compiler contre le nouveau schéma.

- [ ] **Step 3: `app/services/workspaces.py` — helper d'appartenance partagé**

```python
"""Appartenance a un workspace : verifications reutilisees par tous les endpoints
qui exposaient auparavant `_owned_website` (une copie par fichier)."""

from __future__ import annotations

from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.website import Website
from app.models.workspace_member import WorkspaceMember


async def user_workspace_ids(session: AsyncSession, user_id: UUID) -> list[UUID]:
    rows = (
        await session.execute(
            select(WorkspaceMember.workspace_id).where(WorkspaceMember.user_id == user_id)
        )
    ).scalars().all()
    return list(rows)


async def is_member(session: AsyncSession, *, workspace_id: UUID, user_id: UUID) -> bool:
    row = (
        await session.execute(
            select(WorkspaceMember.id).where(
                WorkspaceMember.workspace_id == workspace_id,
                WorkspaceMember.user_id == user_id,
            )
        )
    ).scalar_one_or_none()
    return row is not None


async def owned_website(session: AsyncSession, *, website_id: UUID, user_id: UUID) -> Website:
    site = await session.get(Website, website_id)
    if site is None or not await is_member(session, workspace_id=site.workspace_id, user_id=user_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="site introuvable")
    return site
```

- [ ] **Step 4: Remplacer les 4 copies de `_owned_website` dans les endpoints**

Dans `app/api/v1/endpoints/audit.py`, `advisor.py`, `gtm.py`, `websites.py` : supprimer la
fonction locale `_owned_website` et son import `Website`/`HTTPException` devenu inutile si plus
référencé ; importer `from app.services.workspaces import owned_website` ; remplacer chaque appel
`await _owned_website(session, website_id, user)` par `await owned_website(session,
website_id=website_id, user_id=user.id)` (attention : signature à mots-clés, pas positionnelle).

Dans `app/api/v1/endpoints/websites.py` : les requêtes directes `select(Website).where(
Website.user_id == user.id)` (liste des sites, dédup à la création) deviennent
`select(Website).where(Website.workspace_id.in_(await user_workspace_ids(session, user.id)))`.

Dans `app/api/v1/endpoints/google.py` : `website.user_id != user.id` → passe par `owned_website`
(remplacer l'inline par un appel à la fonction partagée) ; `connection.user_id != user.id` →
`connection.workspace_id not in await user_workspace_ids(session, user.id)` (la vérification
change de sens : c'est le workspace qui possède la connexion, pas l'utilisateur qui clique).

Dans `app/api/v1/endpoints/dev.py` : après avoir trouvé/créé le `User`, trouver ou créer son
workspace :
```python
workspace = (
    await session.execute(
        select(Workspace).join(WorkspaceMember).where(WorkspaceMember.user_id == user.id)
    )
).scalars().first()
if workspace is None:
    workspace = Workspace(name="Dev local", owner_user_id=user.id)
    session.add(workspace)
    await session.flush()
    session.add(WorkspaceMember(workspace_id=workspace.id, user_id=user.id, role="owner"))
    await session.flush()
```
puis `Website(user_id=user.id, ...)` → `Website(workspace_id=workspace.id, ...)` et la requête de
dédup `Website.user_id == user.id` → `Website.workspace_id == workspace.id`.

- [ ] **Step 5: Migration hand-codée**

```bash
cd backend && export PATH="$PATH:/c/Users/DELL/AppData/Roaming/Python/Python312/Scripts"
uv run alembic revision -m "workspaces"
```

Écrire le fichier généré (adapter `down_revision` à la tête actuelle — vérifier avec
`alembic heads` avant d'écrire, ne pas deviner) :

```python
def upgrade() -> None:
    op.create_table(
        "workspaces",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("owner_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"], ondelete="RESTRICT"),
    )
    op.create_index("ix_workspaces_owner_user_id", "workspaces", ["owner_user_id"])

    op.create_table(
        "workspace_members",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("joined_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("workspace_id", "user_id", name="uq_workspace_members_workspace_user"),
    )
    op.create_index("ix_workspace_members_workspace_id", "workspace_members", ["workspace_id"])
    op.create_index("ix_workspace_members_user_id", "workspace_members", ["user_id"])

    op.create_table(
        "workspace_invitations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("invited_email", sa.String(320), nullable=False),
        sa.Column("token", sa.String(64), nullable=False),
        sa.Column("invited_by_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["invited_by_user_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("token", name="uq_workspace_invitations_token"),
    )
    op.create_index("ix_workspace_invitations_workspace_id", "workspace_invitations", ["workspace_id"])
    op.create_index("ix_workspace_invitations_token", "workspace_invitations", ["token"])

    op.create_table(
        "password_reset_tokens",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("token", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("token", name="uq_password_reset_tokens_token"),
    )
    op.create_index("ix_password_reset_tokens_user_id", "password_reset_tokens", ["user_id"])
    op.create_index("ix_password_reset_tokens_token", "password_reset_tokens", ["token"])

    # users : password_hash + google_sub nullable
    op.add_column("users", sa.Column("password_hash", sa.String(255), nullable=True))
    op.alter_column("users", "google_sub", nullable=True)

    # Backfill : un workspace par user existant, lui-meme owner.
    conn = op.get_bind()
    users = conn.execute(sa.text("SELECT id, email, display_name FROM users")).fetchall()
    for user_id, email, display_name in users:
        ws_id = conn.execute(
            sa.text(
                "INSERT INTO workspaces (id, name, owner_user_id, created_at, updated_at) "
                "VALUES (gen_random_uuid(), :name, :owner, now(), now()) RETURNING id"
            ),
            {"name": display_name or email, "owner": user_id},
        ).scalar_one()
        conn.execute(
            sa.text(
                "INSERT INTO workspace_members (id, workspace_id, user_id, role, joined_at) "
                "VALUES (gen_random_uuid(), :ws, :user, 'owner', now())"
            ),
            {"ws": ws_id, "user": user_id},
        )

    # websites : user_id -> workspace_id
    op.add_column("websites", sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=True))
    conn.execute(
        sa.text(
            "UPDATE websites w SET workspace_id = wm.workspace_id "
            "FROM workspace_members wm WHERE wm.user_id = w.user_id"
        )
    )
    op.alter_column("websites", "workspace_id", nullable=False)
    op.drop_constraint("uq_websites_user_domain", "websites", type_="unique")
    op.create_unique_constraint("uq_websites_workspace_domain", "websites", ["workspace_id", "domain"])
    op.drop_column("websites", "user_id")
    op.create_index("ix_websites_workspace_id", "websites", ["workspace_id"])

    # google_connections : meme mecanique
    op.add_column("google_connections", sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=True))
    conn.execute(
        sa.text(
            "UPDATE google_connections gc SET workspace_id = wm.workspace_id "
            "FROM workspace_members wm WHERE wm.user_id = gc.user_id"
        )
    )
    op.alter_column("google_connections", "workspace_id", nullable=False)
    op.drop_constraint("uq_google_connections_user_google_sub", "google_connections", type_="unique")
    op.create_unique_constraint(
        "uq_google_connections_workspace_google_sub", "google_connections", ["workspace_id", "google_sub"]
    )
    op.drop_column("google_connections", "user_id")
    op.create_index("ix_google_connections_workspace_id", "google_connections", ["workspace_id"])

    # advisor_usage : user_id (PK composite) -> workspace_id
    op.add_column("advisor_usage", sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=True))
    conn.execute(
        sa.text(
            "UPDATE advisor_usage au SET workspace_id = wm.workspace_id "
            "FROM workspace_members wm WHERE wm.user_id = au.user_id"
        )
    )
    op.alter_column("advisor_usage", "workspace_id", nullable=False)
    op.drop_constraint("advisor_usage_pkey", "advisor_usage", type_="primary")
    op.drop_column("advisor_usage", "user_id")
    op.create_primary_key("advisor_usage_pkey", "advisor_usage", ["workspace_id", "day"])

    # oauth_states : + workspace_id (nullable, increment B)
    op.add_column("oauth_states", sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key(
        "fk_oauth_states_workspace_id", "oauth_states", "workspaces", ["workspace_id"], ["id"], ondelete="CASCADE"
    )
    op.create_foreign_key(
        "fk_websites_workspace_id", "websites", "workspaces", ["workspace_id"], ["id"], ondelete="CASCADE"
    )
    op.create_foreign_key(
        "fk_google_connections_workspace_id", "google_connections", "workspaces", ["workspace_id"], ["id"], ondelete="CASCADE"
    )
    op.create_foreign_key(
        "fk_advisor_usage_workspace_id", "advisor_usage", "workspaces", ["workspace_id"], ["id"], ondelete="CASCADE"
    )


def downgrade() -> None:
    conn = op.get_bind()

    # oauth_states : retirer la colonne ajoutee (jamais exploitee avant l'increment B).
    op.drop_constraint("fk_oauth_states_workspace_id", "oauth_states", type_="foreignkey")
    op.drop_column("oauth_states", "workspace_id")

    # advisor_usage : workspace_id -> user_id (backfill via owner_user_id du workspace).
    op.drop_constraint("fk_advisor_usage_workspace_id", "advisor_usage", type_="foreignkey")
    op.add_column("advisor_usage", sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True))
    conn.execute(
        sa.text(
            "UPDATE advisor_usage au SET user_id = w.owner_user_id "
            "FROM workspaces w WHERE w.id = au.workspace_id"
        )
    )
    op.alter_column("advisor_usage", "user_id", nullable=False)
    op.drop_constraint("advisor_usage_pkey", "advisor_usage", type_="primary")
    op.drop_column("advisor_usage", "workspace_id")
    op.create_primary_key("advisor_usage_pkey", "advisor_usage", ["user_id", "day"])

    # google_connections : workspace_id -> user_id.
    op.drop_constraint("fk_google_connections_workspace_id", "google_connections", type_="foreignkey")
    op.drop_index("ix_google_connections_workspace_id", table_name="google_connections")
    op.add_column("google_connections", sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True))
    conn.execute(
        sa.text(
            "UPDATE google_connections gc SET user_id = w.owner_user_id "
            "FROM workspaces w WHERE w.id = gc.workspace_id"
        )
    )
    op.alter_column("google_connections", "user_id", nullable=False)
    op.drop_constraint("uq_google_connections_workspace_google_sub", "google_connections", type_="unique")
    op.create_unique_constraint(
        "uq_google_connections_user_google_sub", "google_connections", ["user_id", "google_sub"]
    )
    op.create_index("ix_google_connections_user_id", "google_connections", ["user_id"])
    op.drop_column("google_connections", "workspace_id")

    # websites : workspace_id -> user_id.
    op.drop_constraint("fk_websites_workspace_id", "websites", type_="foreignkey")
    op.drop_index("ix_websites_workspace_id", table_name="websites")
    op.add_column("websites", sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True))
    conn.execute(
        sa.text(
            "UPDATE websites w SET user_id = ws.owner_user_id "
            "FROM workspaces ws WHERE ws.id = w.workspace_id"
        )
    )
    op.alter_column("websites", "user_id", nullable=False)
    op.drop_constraint("uq_websites_workspace_domain", "websites", type_="unique")
    op.create_unique_constraint("uq_websites_user_domain", "websites", ["user_id", "domain"])
    op.create_index("ix_websites_user_id", "websites", ["user_id"])
    op.drop_column("websites", "workspace_id")

    # users : retirer password_hash, remettre google_sub NOT NULL. Hypothese
    # acceptee (etat pre-lancement, aucun compte mot-de-passe-seul reel) :
    # si un compte a ete cree sans google_sub depuis l'upgrade (inscription
    # email/mot de passe), cet ALTER echoue — downgrade non supporte au-dela
    # de ce point sans nettoyage manuel prealable, comme documente au meme
    # titre pour les migrations d'enum de ce projet.
    op.drop_column("users", "password_hash")
    op.alter_column("users", "google_sub", nullable=False)

    op.drop_table("password_reset_tokens")
    op.drop_table("workspace_invitations")
    op.drop_table("workspace_members")
    op.drop_table("workspaces")
```

- [ ] **Step 6: Vérifier la migration**

```bash
cd backend && export PATH="$PATH:/c/Users/DELL/AppData/Roaming/Python/Python312/Scripts"
uv run alembic upgrade head
uv run ruff check app
```
Attendu : migration appliquée sans erreur, `ruff check` propre. `pytest` n'est **pas** attendu
vert à ce stade (fixtures cassées, réparées Task 2) — ne pas lancer la suite complète maintenant.

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "feat(auth): workspaces + migration user_id -> workspace_id (websites, google_connections, advisor_usage)"
```

---

### Task 2: Fixtures de test migrées vers workspace

**Files:**
- Modify: `backend/tests/conftest.py`
- Modify: tous les fichiers de test construisant `Website`/`GoogleConnection`/`AdvisorUsage`
  directement — `test_advisor_chat.py`, `test_advisor_endpoints.py`, `test_advisor_service.py`,
  `test_advisor_tools.py`, `test_audit_endpoints.py`, `test_audit_engine.py`,
  `test_context_builder.py`, `test_gtm_endpoints.py`, `test_link_resource.py`,
  `test_models_journal.py`, `test_models_websites_links.py`, `test_real_audit_probe.py`,
  `test_websites.py` (liste exacte vérifiée par la recherche du Step 1 — s'y fier plutôt qu'à
  cette énumération si elle a bougé).

**Interfaces:**
- Consumes: `app.models.workspace.Workspace`, `app.models.workspace_member.WorkspaceMember`
  (Task 1).
- Produces: `tests/conftest.py::owner_workspace_id(session, user) -> UUID` — utilisée par tous les
  fichiers de test qui construisent un `Website`/`GoogleConnection`/`AdvisorUsage` directement.

- [ ] **Step 1: Recenser tous les call sites à modifier**

```bash
cd backend
grep -rln "Website(user_id\|GoogleConnection(user_id\|AdvisorUsage(user_id" tests/
```
Vérifié à l'écriture de ce plan, cette commande retourne exactement : `test_advisor_chat.py`,
`test_advisor_endpoints.py`, `test_advisor_service.py`, `test_advisor_tools.py`,
`test_audit_endpoints.py`, `test_audit_engine.py`, `test_context_builder.py`,
`test_gtm_endpoints.py`, `test_link_resource.py`, `test_models_journal.py`,
`test_models_websites_links.py`, `test_real_audit_probe.py`, `test_websites.py` — **13 fichiers**,
periometre reel plus large que ce qu'une recherche naïve sur `user_id=user\.id` laisserait croire
(plusieurs fichiers passent une variable locale `user_id` plutôt que l'attribut `user.id`
directement — le pattern ci-dessus cible la syntaxe de construction elle-même, pas la forme de
l'argument, pour ne rater aucun cas). Relancer la commande au moment de l'implémentation : la
liste peut avoir bougé depuis l'écriture de ce plan, faire foi du résultat réel plutôt que de
cette liste figée.

- [ ] **Step 2: `make_user` crée transparemment un workspace**

```python
# tests/conftest.py — ajouter l'import UUID en tete de fichier, modifier make_user
# (ne change PAS sa signature ni son type de retour), ajouter owner_workspace_id.
from uuid import UUID

from app.models.workspace import Workspace
from app.models.workspace_member import WorkspaceMember

@pytest_asyncio.fixture
async def make_user(db_session: AsyncSession) -> UserFactory:
    async def _make(*, sub: str = "sub-user", email: str | None = None,
                    name: str | None = None) -> User:
        user = User(
            email=email or f"{sub}@example.com", google_sub=sub, display_name=name
        )
        db_session.add(user)
        await db_session.flush()
        workspace = Workspace(name=user.display_name or user.email, owner_user_id=user.id)
        db_session.add(workspace)
        await db_session.flush()
        db_session.add(
            WorkspaceMember(workspace_id=workspace.id, user_id=user.id, role="owner")
        )
        await db_session.flush()
        return user

    return _make


async def owner_workspace_id(session: AsyncSession, user: User) -> UUID:
    """Workspace dont `user` est owner — cree transparemment par make_user ci-dessus.
    Fonction ordinaire (pas une fixture) : importable et appelable depuis n'importe
    quel fichier de test avec `from tests.conftest import owner_workspace_id`."""
    return (
        await session.execute(
            select(WorkspaceMember.workspace_id).where(
                WorkspaceMember.user_id == user.id, WorkspaceMember.role == "owner"
            )
        )
    ).scalar_one()
```

Chaque utilisateur créé via `make_user` (donc aussi `authed_client`, qui l'utilise) a maintenant
systématiquement un workspace dont il est `owner` — comportement transparent, aucun test qui ne
s'en soucie pas n'est affecté.

- [ ] **Step 3: Mettre à jour chaque fichier de test recensé au Step 1**

Pour chaque helper local du style :
```python
async def _site(db_session, user_id, domain: str = "tool.test") -> Website:
    site = Website(user_id=user_id, domain=domain, display_name="Tool")
    ...
```
changer la signature pour prendre `workspace_id` au lieu de `user_id`, et au call site :
```python
from tests.conftest import owner_workspace_id
...
user = await make_user(sub="...")
ws_id = await owner_workspace_id(db_session, user)
site = await _site(db_session, ws_id, domain="...")
```
Répéter pour chaque fichier recensé. Idem pour tout `GoogleConnection(user_id=...)` ou
`AdvisorUsage(user_id=...)` construit directement dans un test.

- [ ] **Step 4: Suite complète verte**

```bash
cd backend && export PATH="$PATH:/c/Users/DELL/AppData/Roaming/Python/Python312/Scripts"
.venv/Scripts/python.exe -m pytest -W error -q
uv run ruff check app tests
```
Attendu : tous les tests existants passent de nouveau (aucun nouveau test n'est ajouté dans cette
tâche — c'est une migration pure des fixtures).

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "test: migre les fixtures existantes vers workspace_id"
```

---

### Task 3: Hash de mot de passe

**Files:**
- Create: `backend/app/security/password.py`
- Test: `backend/tests/test_password.py`
- Modify: `backend/pyproject.toml` (ajout `argon2-cffi`)

**Interfaces:**
- Produces: `hash_password(plain: str) -> str`, `verify_password(plain: str, hashed: str) ->
  bool`. Consommé par Task 6 (register/login).

- [ ] **Step 1: Ajouter la dépendance**

```bash
cd backend && export PATH="$PATH:/c/Users/DELL/AppData/Roaming/Python/Python312/Scripts"
uv add argon2-cffi
```

- [ ] **Step 2: Écrire le test qui échoue**

```python
# tests/test_password.py
from app.security.password import hash_password, verify_password


def test_hash_password_verifies_correctly() -> None:
    hashed = hash_password("correct horse battery staple")
    assert verify_password("correct horse battery staple", hashed) is True


def test_verify_password_rejects_wrong_password() -> None:
    hashed = hash_password("correct horse battery staple")
    assert verify_password("wrong password", hashed) is False


def test_hash_password_is_not_plaintext() -> None:
    hashed = hash_password("secret")
    assert "secret" not in hashed


def test_verify_password_rejects_malformed_hash() -> None:
    # Un hash corrompu/vide ne doit jamais lever, juste renvoyer False.
    assert verify_password("secret", "not-a-real-hash") is False
```

Run: `pytest tests/test_password.py -v` — Expected: FAIL (`ModuleNotFoundError`).

- [ ] **Step 3: Implémentation**

```python
# app/security/password.py
"""Hash de mot de passe (Argon2id, via argon2-cffi — recommandation actuelle,
`passlib` n'est plus activement maintenu)."""

from __future__ import annotations

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, InvalidHashError

_hasher = PasswordHasher()


def hash_password(plain: str) -> str:
    return _hasher.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return _hasher.verify(hashed, plain)
    except (VerifyMismatchError, InvalidHashError, ValueError):
        return False
```

- [ ] **Step 4: Run + ruff**

```bash
cd backend && export PATH="$PATH:/c/Users/DELL/AppData/Roaming/Python/Python312/Scripts"
.venv/Scripts/python.exe -m pytest tests/test_password.py -v
uv run ruff check app/security/password.py tests/test_password.py
```
Expected: 4 passed, ruff propre.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat(auth): hash de mot de passe (argon2-cffi)"
```

---

### Task 4: Interface d'envoi d'email

**Files:**
- Create: `backend/app/services/email/__init__.py`, `backend/app/services/email/base.py`,
  `backend/app/services/email/console.py`
- Modify: `backend/app/api/deps.py`
- Test: `backend/tests/test_email.py`

**Interfaces:**
- Produces: `EmailSender` (ABC, méthode `send(*, to, subject, body_text) -> None`),
  `ConsoleEmailSender`, `deps.get_email_sender() -> EmailSender`, `EmailSenderDep`. Consommé par
  Task 5 (invitations) et Task 7 (reset de mot de passe).

- [ ] **Step 1: Écrire le test qui échoue**

```python
# tests/test_email.py
import logging

import pytest

from app.services.email import ConsoleEmailSender


async def test_console_email_sender_logs_content(caplog) -> None:
    sender = ConsoleEmailSender()
    with caplog.at_level(logging.INFO):
        await sender.send(to="a@b.test", subject="Bienvenue", body_text="Voici le lien : https://x")
    assert "a@b.test" in caplog.text
    assert "https://x" in caplog.text
```

Run: `pytest tests/test_email.py -v` — Expected: FAIL (`ImportError`).

- [ ] **Step 2: Implémentation**

```python
# app/services/email/base.py
from __future__ import annotations

from abc import ABC, abstractmethod


class EmailSender(ABC):
    @abstractmethod
    async def send(self, *, to: str, subject: str, body_text: str) -> None: ...
```

```python
# app/services/email/console.py
from __future__ import annotations

import logging

from app.services.email.base import EmailSender

logger = logging.getLogger(__name__)


class ConsoleEmailSender(EmailSender):
    """Dev : logue le contenu (avec le lien) au lieu d'envoyer. Jamais de vrai reseau."""

    async def send(self, *, to: str, subject: str, body_text: str) -> None:
        logger.info("EMAIL (console) to=%s subject=%s\n%s", to, subject, body_text)
```

```python
# app/services/email/__init__.py
from app.services.email.base import EmailSender
from app.services.email.console import ConsoleEmailSender

__all__ = ["EmailSender", "ConsoleEmailSender"]
```

Dans `app/api/deps.py`, ajouter :
```python
from app.services.email import ConsoleEmailSender, EmailSender


def get_email_sender() -> EmailSender:
    # Aucun fournisseur reel configure pour l'instant (choix differe, voir spec §6/§9).
    return ConsoleEmailSender()


EmailSenderDep = Annotated[EmailSender, Depends(get_email_sender)]
```

- [ ] **Step 3: Run + ruff**

```bash
cd backend && export PATH="$PATH:/c/Users/DELL/AppData/Roaming/Python/Python312/Scripts"
.venv/Scripts/python.exe -m pytest tests/test_email.py -v
uv run ruff check app/services/email app/api/deps.py tests/test_email.py
```
Expected: 1 passed, ruff propre.

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "feat(email): interface EmailSender + implementation console (dev)"
```

---

### Task 5: Service workspaces — création, invitation, acceptation (logique pure)

**Files:**
- Create: `backend/app/services/workspace_invites.py`
- Modify: `backend/app/services/workspaces.py` (Task 1) — ajout de `create_workspace_for_user`
- Test: `backend/tests/test_workspace_invites.py`

**Interfaces:**
- Consumes: `app.services.workspaces.is_member` (Task 1), `EmailSender` (Task 4).
- Produces: `workspaces.create_workspace_for_user(session, *, user, name=None) -> Workspace` ;
  `workspace_invites.create_invitation(session, *, workspace_id, invited_email,
  invited_by_user_id) -> WorkspaceInvitation` ; `workspace_invites.accept_invitation(session, *,
  token, user) -> WorkspaceMember` (lève `InvitationInvalid`, `InvitationEmailMismatch`) ;
  `workspace_invites.get_invitation(session, token) -> WorkspaceInvitation | None`. Consommé par
  Task 6 (register) et Task 9 (endpoints workspace).

- [ ] **Step 1: Écrire les tests qui échouent**

```python
# tests/test_workspace_invites.py
from datetime import UTC, datetime, timedelta

import pytest

from app.models.workspace_invitation import WorkspaceInvitation
from app.models.workspace_member import WorkspaceMember
from app.services.workspace_invites import (
    InvitationEmailMismatch,
    InvitationInvalid,
    accept_invitation,
    create_invitation,
    get_invitation,
)
from app.services.workspaces import create_workspace_for_user
from tests.conftest import owner_workspace_id


async def test_create_workspace_for_user_makes_owner_membership(db_session, make_user) -> None:
    user = await make_user(sub="ws-1")
    workspace = await create_workspace_for_user(db_session, user=user, name="Mon espace")
    assert workspace.owner_user_id == user.id
    assert workspace.name == "Mon espace"


async def test_create_invitation_has_token_and_expiry(db_session, make_user) -> None:
    owner = await make_user(sub="inv-owner")
    ws_id = await owner_workspace_id(db_session, owner)
    invitation = await create_invitation(
        db_session, workspace_id=ws_id, invited_email="friend@example.com",
        invited_by_user_id=owner.id,
    )
    assert invitation.status == "pending"
    assert invitation.token
    assert invitation.expires_at > datetime.now(UTC)


async def test_accept_invitation_creates_membership(db_session, make_user) -> None:
    owner = await make_user(sub="inv-owner-2")
    ws_id = await owner_workspace_id(db_session, owner)
    invitation = await create_invitation(
        db_session, workspace_id=ws_id, invited_email="friend2@example.com",
        invited_by_user_id=owner.id,
    )
    friend = await make_user(sub="friend-2", email="friend2@example.com")

    member = await accept_invitation(db_session, token=invitation.token, user=friend)

    assert member.workspace_id == ws_id
    assert member.role == "member"
    refreshed = await db_session.get(WorkspaceInvitation, invitation.id)
    assert refreshed.status == "accepted"
    assert refreshed.accepted_at is not None


async def test_accept_invitation_rejects_email_mismatch(db_session, make_user) -> None:
    owner = await make_user(sub="inv-owner-3")
    ws_id = await owner_workspace_id(db_session, owner)
    invitation = await create_invitation(
        db_session, workspace_id=ws_id, invited_email="expected@example.com",
        invited_by_user_id=owner.id,
    )
    someone_else = await make_user(sub="someone-else", email="someone@example.com")

    with pytest.raises(InvitationEmailMismatch):
        await accept_invitation(db_session, token=invitation.token, user=someone_else)


async def test_accept_invitation_rejects_expired(db_session, make_user) -> None:
    owner = await make_user(sub="inv-owner-4")
    ws_id = await owner_workspace_id(db_session, owner)
    invitation = await create_invitation(
        db_session, workspace_id=ws_id, invited_email="friend4@example.com",
        invited_by_user_id=owner.id,
    )
    invitation.expires_at = datetime.now(UTC) - timedelta(days=1)
    await db_session.flush()
    friend = await make_user(sub="friend-4", email="friend4@example.com")

    with pytest.raises(InvitationInvalid):
        await accept_invitation(db_session, token=invitation.token, user=friend)


async def test_accept_invitation_rejects_already_used_token(db_session, make_user) -> None:
    owner = await make_user(sub="inv-owner-5")
    ws_id = await owner_workspace_id(db_session, owner)
    invitation = await create_invitation(
        db_session, workspace_id=ws_id, invited_email="friend5@example.com",
        invited_by_user_id=owner.id,
    )
    friend = await make_user(sub="friend-5", email="friend5@example.com")
    await accept_invitation(db_session, token=invitation.token, user=friend)

    with pytest.raises(InvitationInvalid):
        await accept_invitation(db_session, token=invitation.token, user=friend)


async def test_get_invitation_unknown_token_returns_none(db_session) -> None:
    assert await get_invitation(db_session, "not-a-real-token") is None
```

Run: `pytest tests/test_workspace_invites.py -v` — Expected: FAIL (`ModuleNotFoundError`).

- [ ] **Step 2: Implémentation**

```python
# app/services/workspaces.py — ajouter a la fin du fichier cree en Task 1
from app.models.workspace import Workspace


async def create_workspace_for_user(
    session: AsyncSession, *, user: "User", name: str | None = None
) -> Workspace:
    workspace = Workspace(name=name or user.display_name or user.email, owner_user_id=user.id)
    session.add(workspace)
    await session.flush()
    session.add(WorkspaceMember(workspace_id=workspace.id, user_id=user.id, role="owner"))
    await session.flush()
    return workspace
```
(ajouter `from app.models.user import User` sous `TYPE_CHECKING` pour l'annotation si non deja
present dans le fichier.)

```python
# app/services/workspace_invites.py
"""Invitations a rejoindre un workspace : creation, consultation, acceptation."""

from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.models.workspace_invitation import WorkspaceInvitation
from app.models.workspace_member import WorkspaceMember

_INVITATION_TTL = timedelta(days=7)


class InvitationInvalid(Exception):
    """Token inconnu, expire ou deja utilise/revoque."""


class InvitationEmailMismatch(Exception):
    """L'utilisateur qui accepte n'a pas l'email invite."""


async def create_invitation(
    session: AsyncSession, *, workspace_id: UUID, invited_email: str, invited_by_user_id: UUID
) -> WorkspaceInvitation:
    invitation = WorkspaceInvitation(
        workspace_id=workspace_id,
        invited_email=invited_email,
        token=secrets.token_urlsafe(32),
        invited_by_user_id=invited_by_user_id,
        status="pending",
        expires_at=datetime.now(UTC) + _INVITATION_TTL,
    )
    session.add(invitation)
    await session.flush()
    return invitation


async def get_invitation(session: AsyncSession, token: str) -> WorkspaceInvitation | None:
    return (
        await session.execute(
            select(WorkspaceInvitation).where(WorkspaceInvitation.token == token)
        )
    ).scalar_one_or_none()


async def accept_invitation(
    session: AsyncSession, *, token: str, user: User
) -> WorkspaceMember:
    invitation = await get_invitation(session, token)
    if invitation is None or invitation.status != "pending":
        raise InvitationInvalid("invitation introuvable ou deja utilisee")
    if invitation.expires_at < datetime.now(UTC):
        raise InvitationInvalid("invitation expiree")
    if invitation.invited_email.lower() != user.email.lower():
        raise InvitationEmailMismatch("cette invitation est nominative")

    member = WorkspaceMember(workspace_id=invitation.workspace_id, user_id=user.id, role="member")
    session.add(member)
    invitation.status = "accepted"
    invitation.accepted_at = datetime.now(UTC)
    await session.flush()
    return member
```

- [ ] **Step 3: Run + ruff**

```bash
cd backend && export PATH="$PATH:/c/Users/DELL/AppData/Roaming/Python/Python312/Scripts"
.venv/Scripts/python.exe -m pytest tests/test_workspace_invites.py -v
uv run ruff check app/services/workspaces.py app/services/workspace_invites.py tests/test_workspace_invites.py
```
Expected: 7 passed, ruff propre.

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "feat(workspaces): creation de workspace + invitations (logique pure)"
```

---

### Task 6: Endpoints `POST /auth/register`, `/auth/login`, `/auth/logout`

**Files:**
- Modify: `backend/app/api/v1/endpoints/auth.py`
- Test: `backend/tests/test_auth_password.py`

**Interfaces:**
- Consumes: `app.security.password.{hash_password,verify_password}` (Task 3),
  `app.services.workspaces.create_workspace_for_user` (Task 5).
- Produces: `POST /auth/register`, `POST /auth/login`, `POST /auth/logout`.

- [ ] **Step 1: Écrire les tests qui échouent**

```python
# tests/test_auth_password.py
from httpx import AsyncClient
from sqlalchemy import select

from app.models.user import User
from app.models.workspace_member import WorkspaceMember


async def test_register_creates_user_and_workspace(db_client: AsyncClient) -> None:
    resp = await db_client.post(
        "/api/v1/auth/register",
        json={"email": "new@example.com", "password": "correct horse battery staple", "display_name": "New"},
    )
    assert resp.status_code == 201, resp.text
    assert "cc_session" in resp.cookies


async def test_register_rejects_duplicate_password_email(
    db_client: AsyncClient, db_session
) -> None:
    await db_client.post(
        "/api/v1/auth/register",
        json={"email": "dup@example.com", "password": "correct horse battery staple", "display_name": "Dup"},
    )
    resp = await db_client.post(
        "/api/v1/auth/register",
        json={"email": "dup@example.com", "password": "another password here", "display_name": "Dup2"},
    )
    assert resp.status_code == 409


async def test_register_rejects_email_used_by_google_account(
    db_client: AsyncClient, db_session, make_user
) -> None:
    await make_user(sub="google-user", email="google@example.com")
    resp = await db_client.post(
        "/api/v1/auth/register",
        json={"email": "google@example.com", "password": "correct horse battery staple", "display_name": "X"},
    )
    assert resp.status_code == 409
    assert "google" in resp.json()["detail"].lower()


async def test_login_succeeds_with_correct_password(db_client: AsyncClient) -> None:
    await db_client.post(
        "/api/v1/auth/register",
        json={"email": "login@example.com", "password": "correct horse battery staple", "display_name": "L"},
    )
    db_client.cookies.clear()
    resp = await db_client.post(
        "/api/v1/auth/login", json={"email": "login@example.com", "password": "correct horse battery staple"}
    )
    assert resp.status_code == 200
    assert "cc_session" in resp.cookies


async def test_login_rejects_wrong_password(db_client: AsyncClient) -> None:
    await db_client.post(
        "/api/v1/auth/register",
        json={"email": "wrongpw@example.com", "password": "correct horse battery staple", "display_name": "W"},
    )
    db_client.cookies.clear()
    resp = await db_client.post(
        "/api/v1/auth/login", json={"email": "wrongpw@example.com", "password": "nope nope nope"}
    )
    assert resp.status_code == 400


async def test_login_rejects_google_only_account(db_client: AsyncClient, make_user) -> None:
    await make_user(sub="g-only", email="gonly@example.com")
    resp = await db_client.post(
        "/api/v1/auth/login", json={"email": "gonly@example.com", "password": "anything"}
    )
    assert resp.status_code == 400
    assert "google" in resp.json()["detail"].lower()


async def test_login_unknown_email_returns_400(db_client: AsyncClient) -> None:
    resp = await db_client.post(
        "/api/v1/auth/login", json={"email": "nobody@example.com", "password": "anything"}
    )
    assert resp.status_code == 400


async def test_logout_clears_session_cookie(db_client: AsyncClient) -> None:
    await db_client.post(
        "/api/v1/auth/register",
        json={"email": "logout@example.com", "password": "correct horse battery staple", "display_name": "O"},
    )
    resp = await db_client.post("/api/v1/auth/logout")
    assert resp.status_code == 204
    # Le cookie renvoye est vide/expire — httpx applique le Set-Cookie, donc
    # une requete authentifiee suivante echoue.
    me = await db_client.get("/api/v1/auth/me")
    assert me.status_code == 401
```

Run: `pytest tests/test_auth_password.py -v` — Expected: FAIL (404, routes inexistantes).

- [ ] **Step 2: Implémentation**

Dans `app/api/v1/endpoints/auth.py`, ajouter :

```python
from pydantic import EmailStr

from app.security.password import hash_password, verify_password
from app.services.workspaces import create_workspace_for_user


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str
    display_name: str | None = None


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


def _set_session_cookie(response: Response, user_id, settings) -> None:
    response.set_cookie(
        settings.session_cookie_name,
        issue_session(user_id, secret=settings.app_secret_key.get_secret_value()),
        max_age=_SESSION_MAX_AGE,
        httponly=True,
        samesite="lax",
        secure=settings.environment != "local",
    )


@router.post("/register", status_code=status.HTTP_201_CREATED)
async def register(
    body: RegisterRequest, response: Response, session: SessionDep, settings: SettingsDep
) -> None:
    existing = (
        await session.execute(select(User).where(User.email == body.email))
    ).scalar_one_or_none()
    if existing is not None:
        detail = (
            "ce compte utilise deja Google, connecte-toi avec Google"
            if existing.google_sub is not None
            else "email deja utilise"
        )
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=detail)

    user = User(
        email=body.email,
        password_hash=hash_password(body.password),
        google_sub=None,
        display_name=body.display_name,
    )
    session.add(user)
    await session.flush()
    await create_workspace_for_user(session, user=user)
    await session.commit()
    _set_session_cookie(response, user.id, settings)


@router.post("/login")
async def login(
    body: LoginRequest, response: Response, session: SessionDep, settings: SettingsDep
) -> None:
    user = (
        await session.execute(select(User).where(User.email == body.email))
    ).scalar_one_or_none()
    if user is None or user.password_hash is None:
        detail = (
            "ce compte utilise Google, pas de mot de passe"
            if user is not None
            else "email ou mot de passe incorrect"
        )
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)
    if not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="email ou mot de passe incorrect")
    _set_session_cookie(response, user.id, settings)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(response: Response, settings: SettingsDep) -> None:
    response.delete_cookie(settings.session_cookie_name)


class MeOut(BaseModel):
    id: UUID
    email: str
    display_name: str | None


@router.get("/me", response_model=MeOut)
async def me(user: CurrentUserDep) -> MeOut:
    return MeOut(id=user.id, email=user.email, display_name=user.display_name)
```

Import `CurrentUserDep` depuis `app.api.deps` en tête de fichier, et `Response` depuis
`fastapi`, `User` depuis `app.models.user` (déjà présents ou à ajouter selon l'état actuel du
fichier).

- [ ] **Step 3: Run + ruff**

```bash
cd backend && export PATH="$PATH:/c/Users/DELL/AppData/Roaming/Python/Python312/Scripts"
.venv/Scripts/python.exe -m pytest tests/test_auth_password.py -v
uv run ruff check app/api/v1/endpoints/auth.py tests/test_auth_password.py
```
Expected: 8 passed, ruff propre.

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "feat(auth): inscription/connexion/deconnexion email + mot de passe, GET /auth/me"
```

---

### Task 7: Réinitialisation de mot de passe

**Files:**
- Modify: `backend/app/api/v1/endpoints/auth.py`
- Test: `backend/tests/test_password_reset.py`

**Interfaces:**
- Consumes: `EmailSenderDep` (Task 4), `hash_password` (Task 3).
- Produces: `POST /auth/password-reset/request`, `POST /auth/password-reset/confirm`.

- [ ] **Step 1: Écrire les tests qui échouent**

```python
# tests/test_password_reset.py
import secrets
from datetime import UTC, datetime, timedelta

from httpx import AsyncClient

from app.models.password_reset_token import PasswordResetToken


async def test_reset_request_always_returns_200(db_client: AsyncClient) -> None:
    resp = await db_client.post("/api/v1/auth/password-reset/request", json={"email": "unknown@example.com"})
    assert resp.status_code == 200  # ne revele pas si le compte existe


async def test_reset_confirm_updates_password(db_client: AsyncClient, db_session) -> None:
    await db_client.post(
        "/api/v1/auth/register",
        json={"email": "reset@example.com", "password": "old password here", "display_name": "R"},
    )
    await db_client.post("/api/v1/auth/password-reset/request", json={"email": "reset@example.com"})
    token_row = (
        await db_session.execute(
            __import__("sqlalchemy").select(PasswordResetToken).order_by(PasswordResetToken.created_at.desc())
        )
    ).scalars().first()

    resp = await db_client.post(
        "/api/v1/auth/password-reset/confirm",
        json={"token": token_row.token, "new_password": "new password here"},
    )
    assert resp.status_code == 200

    db_client.cookies.clear()
    login = await db_client.post(
        "/api/v1/auth/login", json={"email": "reset@example.com", "password": "new password here"}
    )
    assert login.status_code == 200


async def test_reset_confirm_rejects_expired_token(db_client: AsyncClient, db_session) -> None:
    await db_client.post(
        "/api/v1/auth/register",
        json={"email": "expired@example.com", "password": "old password here", "display_name": "E"},
    )
    from app.models.user import User
    user = (
        await db_session.execute(__import__("sqlalchemy").select(User).where(User.email == "expired@example.com"))
    ).scalar_one()
    db_session.add(
        PasswordResetToken(
            user_id=user.id, token=secrets.token_urlsafe(32),
            expires_at=datetime.now(UTC) - timedelta(hours=1),
        )
    )
    await db_session.flush()
    token_row = (
        await db_session.execute(
            __import__("sqlalchemy").select(PasswordResetToken).where(PasswordResetToken.user_id == user.id)
        )
    ).scalars().first()

    resp = await db_client.post(
        "/api/v1/auth/password-reset/confirm",
        json={"token": token_row.token, "new_password": "new password here"},
    )
    assert resp.status_code == 400


async def test_reset_confirm_rejects_reused_token(db_client: AsyncClient, db_session) -> None:
    await db_client.post(
        "/api/v1/auth/register",
        json={"email": "reused@example.com", "password": "old password here", "display_name": "U"},
    )
    await db_client.post("/api/v1/auth/password-reset/request", json={"email": "reused@example.com"})
    token_row = (
        await db_session.execute(
            __import__("sqlalchemy").select(PasswordResetToken).order_by(PasswordResetToken.created_at.desc())
        )
    ).scalars().first()
    await db_client.post(
        "/api/v1/auth/password-reset/confirm",
        json={"token": token_row.token, "new_password": "new password here"},
    )
    resp = await db_client.post(
        "/api/v1/auth/password-reset/confirm",
        json={"token": token_row.token, "new_password": "yet another one"},
    )
    assert resp.status_code == 400
```

(Les `__import__("sqlalchemy")` inline évitent un import dupliqué dans ce brouillon de plan —
l'implémenteur doit les remplacer par un `from sqlalchemy import select` propre en tête de
fichier lors de l'écriture réelle du test.)

Run: `pytest tests/test_password_reset.py -v` — Expected: FAIL (404, routes inexistantes).

- [ ] **Step 2: Implémentation**

```python
# app/api/v1/endpoints/auth.py — ajouter
import secrets
from datetime import UTC, datetime, timedelta

from app.api.deps import EmailSenderDep
from app.models.password_reset_token import PasswordResetToken

_RESET_TTL = timedelta(hours=1)


class PasswordResetRequest(BaseModel):
    email: EmailStr


class PasswordResetConfirm(BaseModel):
    token: str
    new_password: str


@router.post("/password-reset/request")
async def password_reset_request(
    body: PasswordResetRequest, session: SessionDep, settings: SettingsDep, email_sender: EmailSenderDep
) -> dict[str, str]:
    user = (
        await session.execute(
            select(User).where(User.email == body.email, User.password_hash.is_not(None))
        )
    ).scalar_one_or_none()
    if user is not None:
        token = secrets.token_urlsafe(32)
        session.add(
            PasswordResetToken(
                user_id=user.id, token=token, expires_at=datetime.now(UTC) + _RESET_TTL
            )
        )
        await session.commit()
        link = f"{settings.frontend_base_url}/reset-password?token={token}"
        await email_sender.send(
            to=user.email, subject="Réinitialisation de mot de passe",
            body_text=f"Clique ici pour choisir un nouveau mot de passe : {link}",
        )
    return {"status": "ok"}  # toujours 200, meme si l'email n'existe pas


@router.post("/password-reset/confirm")
async def password_reset_confirm(
    body: PasswordResetConfirm, session: SessionDep
) -> dict[str, str]:
    row = (
        await session.execute(
            select(PasswordResetToken).where(PasswordResetToken.token == body.token)
        )
    ).scalar_one_or_none()
    if row is None or row.used_at is not None or row.expires_at < datetime.now(UTC):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="lien invalide ou expire")

    user = await session.get(User, row.user_id)
    user.password_hash = hash_password(body.new_password)
    row.used_at = datetime.now(UTC)
    await session.commit()
    return {"status": "ok"}
```

- [ ] **Step 3: Run + ruff**

```bash
cd backend && export PATH="$PATH:/c/Users/DELL/AppData/Roaming/Python/Python312/Scripts"
.venv/Scripts/python.exe -m pytest tests/test_password_reset.py -v
uv run ruff check app/api/v1/endpoints/auth.py tests/test_password_reset.py
```
Expected: 4 passed, ruff propre.

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "feat(auth): reinitialisation de mot de passe par email"
```

---

### Task 8: Login Google — scopes identité seule, séparé de la connexion de données

**Files:**
- Modify: `backend/app/services/google_oauth/base.py`, `real.py`, `mock.py`
- Modify: `backend/app/api/v1/endpoints/auth.py` (`google_start`, `google_callback`)
- Modify: `backend/tests/test_auth_flow.py` (fichier existant confirmé — retrait de 2 tests
  devenus incorrects, réécriture d'un 3ᵉ)
- Create: `backend/tests/test_auth_google_login.py`

**Interfaces:**
- Produces: `GOOGLE_LOGIN_SCOPES` (tuple), remplace l'usage de `GOOGLE_OAUTH_SCOPES` dans le flow
  de login. `GOOGLE_OAUTH_SCOPES` reste défini (renommer en `GOOGLE_DATA_SCOPES` si plus clair)
  pour l'incrément B, mais n'est plus utilisé par ce plan.
- Breaking change assumé : `google_start` perd le paramètre `current_user`/le lien
  `state.user_id` pour le cas "ajouter une connexion en étant déjà connecté" — ce cas devient
  l'endpoint séparé `/connections/google/start` de l'incrément B (§7 de la spec), pas
  `/auth/google/start`. `redirect_to` est conservé (utile pour revenir sur la bonne page après un
  login, ex. depuis `/invitations/{token}`).

- [ ] **Step 1: Retirer les tests devenus incorrects, réécrire celui qui vérifiait la connexion**

Dans `tests/test_auth_flow.py`, **supprimer entièrement** ces deux tests (leur scénario
n'existe plus une fois le login séparé de la connexion de données — `test_reauth_...` suppose
qu'un login crée une connexion, `test_logged_in_user_adds_second_account` suppose qu'on peut
ajouter une connexion via `/auth/google/start` en étant déjà connecté, ce qui devient le rôle de
`/connections/google/start` dans l'incrément B) :
- `test_reauth_updates_connection_without_duplicate`
- `test_logged_in_user_adds_second_account`

Remplacer `test_callback_logs_in_creates_user_and_encrypted_connection` par :

```python
async def test_callback_logs_in_creates_user(
    db_client: AsyncClient, db_session: AsyncSession
) -> None:
    state = await _start(db_client)
    resp = await db_client.get(
        "/api/v1/auth/google/callback",
        params={"code": "mock:client_perso", "state": state},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert resp.headers["location"] == "http://localhost:4000"
    assert "cc_session" in resp.cookies

    user = (
        await db_session.execute(select(User).where(User.google_sub == "google-sub-client-perso"))
    ).scalar_one()
    assert user.email == "client.perso@gmail.com"
```

(Retirer les imports devenus inutiles dans ce fichier — `ConnectionStatus`, `GoogleConnection` —
si plus référencés ailleurs dans le fichier ; vérifier avec `ruff check`.) Les 4 tests restants
(`test_start_generates_pkce_challenge_and_persists_state`, `test_state_is_single_use`,
`test_callback_rejects_unknown_state`, `test_callback_rejects_denied_consent`) ne changent pas.

Run pour confirmer le rouge (les 2 tests supprimés ne comptent plus, celui réécrit échoue tant
que Step 3 n'est pas fait — mais échoue pour une raison différente : il passe déjà tel quel
puisqu'on n'a fait qu'enlever des assertions ; le vrai rouge attendu ici vient plutôt du nouveau
fichier ci-dessous) :

```bash
cd backend && export PATH="$PATH:/c/Users/DELL/AppData/Roaming/Python/Python312/Scripts"
.venv/Scripts/python.exe -m pytest tests/test_auth_flow.py -v
```

- [ ] **Step 2: Écrire les nouveaux tests qui échouent**

```python
# tests/test_auth_google_login.py
"""Login Google en scopes identite seule : pas de connexion de donnees creee,
garde-fou contre la fusion silencieuse avec un compte mot de passe existant."""

from urllib.parse import parse_qs, urlparse

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.google_connection import GoogleConnection
from app.models.user import User
from app.models.workspace_member import WorkspaceMember


def _query(url: str) -> dict[str, str]:
    return {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}


async def _start(client: AsyncClient) -> str:
    resp = await client.get("/api/v1/auth/google/start")
    assert resp.status_code == 200, resp.text
    return _query(resp.json()["authorization_url"])["state"]


async def test_google_login_does_not_create_google_connection(
    db_client: AsyncClient, db_session: AsyncSession
) -> None:
    state = await _start(db_client)
    resp = await db_client.get(
        "/api/v1/auth/google/callback",
        params={"code": "mock:client_perso", "state": state},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    conns = (await db_session.execute(select(GoogleConnection))).scalars().all()
    assert conns == []


async def test_google_login_new_user_gets_own_workspace(
    db_client: AsyncClient, db_session: AsyncSession
) -> None:
    state = await _start(db_client)
    resp = await db_client.get(
        "/api/v1/auth/google/callback",
        params={"code": "mock:dev_agence", "state": state},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert "cc_session" in resp.cookies

    user = (
        await db_session.execute(select(User).where(User.google_sub == "google-sub-dev-agence"))
    ).scalar_one()
    membership = (
        await db_session.execute(select(WorkspaceMember).where(WorkspaceMember.user_id == user.id))
    ).scalar_one()
    assert membership.role == "owner"


async def test_google_login_rejects_email_already_password_based(
    db_client: AsyncClient,
) -> None:
    await db_client.post(
        "/api/v1/auth/register",
        json={
            "email": "client.perso@gmail.com",  # meme email que la fixture mock "client_perso"
            "password": "correct horse battery staple",
            "display_name": "Deja inscrit",
        },
    )
    db_client.cookies.clear()
    state = await _start(db_client)
    resp = await db_client.get(
        "/api/v1/auth/google/callback",
        params={"code": "mock:client_perso", "state": state},
        follow_redirects=False,
    )
    assert resp.status_code == 400
    assert "mot de passe" in resp.json()["detail"].lower()
```

Run: `pytest tests/test_auth_google_login.py -v` — Expected: FAIL (`GoogleConnection` toujours
créée par le code actuel, `client.perso@gmail.com` accepte encore un login Google en doublon).

- [ ] **Step 3: Implémentation**

```python
# app/services/google_oauth/base.py — ajouter a cote de GOOGLE_OAUTH_SCOPES existant
GOOGLE_LOGIN_SCOPES: tuple[str, ...] = ("openid", "email", "profile")
# GOOGLE_OAUTH_SCOPES (renomme en GOOGLE_DATA_SCOPES si plus clair a l'usage) reste
# tel quel pour l'increment B — non utilise par ce plan.
```

`real.py` : la méthode qui construit l'URL d'autorisation doit accepter les scopes en paramètre
plutôt que de coder en dur `GOOGLE_OAUTH_SCOPES` :
```python
def build_authorization_url(
    self, *, state, code_challenge, login_hint=None, scopes: tuple[str, ...] = GOOGLE_LOGIN_SCOPES
) -> str:
    ...
    "scope": " ".join(scopes),
    ...
```
`mock.py` : même changement de signature (ajouter `scopes: tuple[str, ...] =
GOOGLE_LOGIN_SCOPES` en paramètre, cohérent avec `real.py`) ; `base.py` (méthode abstraite) mise
à jour en conséquence si sa signature liste les paramètres explicitement.

Dans `auth.py::google_start`, retirer le paramètre `current_user: OptionalUserDep` et
`login_hint` qui en dépendait :
```python
@router.get("/start", response_model=StartResponse)
async def google_start(
    session: SessionDep,
    settings: SettingsDep,
    client: GoogleClientDep,
    redirect_to: str | None = None,
) -> StartResponse:
    transaction = await create_oauth_transaction(
        session, user_id=None, redirect_to=redirect_to, ttl_seconds=settings.oauth_state_ttl_seconds,
    )
    await session.commit()
    url = client.build_authorization_url(
        state=transaction.state, code_challenge=transaction.code_challenge,
    )
    return StartResponse(authorization_url=url)
```

Dans `auth.py::google_callback` : supprimer l'appel à `upsert_google_connection` et toute la
branche `if consumed.user_id is not None` (devenue impossible : `state.user_id` est toujours
`None` depuis `google_start` ci-dessus) ; avant de créer un nouvel utilisateur, vérifier qu'aucun
compte mot de passe n'utilise déjà cet email :

```python
user = (
    await session.execute(select(User).where(User.google_sub == userinfo.sub))
).scalar_one_or_none()
if user is None:
    existing_password_user = (
        await session.execute(
            select(User).where(User.email == userinfo.email, User.password_hash.is_not(None))
        )
    ).scalar_one_or_none()
    if existing_password_user is not None:
        await session.commit()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="ce compte utilise deja un mot de passe, connecte-toi avec ton mot de passe",
        )
    user = User(email=userinfo.email, google_sub=userinfo.sub, display_name=userinfo.name)
    session.add(user)
    await session.flush()
    await create_workspace_for_user(session, user=user)
await session.commit()
```

Retirer les imports devenus inutiles (`TokenCipherDep`, `upsert_google_connection`,
`OptionalUserDep` si plus utilisé ailleurs dans le fichier) — laisser `ruff check` confirmer.

- [ ] **Step 4: Run + ruff**

```bash
cd backend && export PATH="$PATH:/c/Users/DELL/AppData/Roaming/Python/Python312/Scripts"
.venv/Scripts/python.exe -m pytest tests/test_auth_google_login.py -v
uv run ruff check app/services/google_oauth app/api/v1/endpoints/auth.py
```
Expected: tests passent, ruff propre.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat(auth): login Google en scopes identite seule, separe de la connexion de donnees"
```

---

### Task 9: Endpoints workspaces (liste, invitation, acceptation, retrait de membre)

**Files:**
- Create: `backend/app/api/v1/endpoints/workspaces.py`
- Modify: `backend/app/api/v1/router.py`
- Test: `backend/tests/test_workspaces_endpoints.py`

**Interfaces:**
- Consumes: `app.services.workspace_invites.*` (Task 5), `app.services.workspaces.is_member`
  (Task 1), `EmailSenderDep` (Task 4).
- Produces: `GET /workspaces/mine`, `POST /workspaces/{id}/invitations`, `GET
  /invitations/{token}`, `POST /invitations/{token}/accept`, `DELETE
  /workspaces/{id}/members/{user_id}`.

- [ ] **Step 1: Écrire les tests qui échouent**

```python
# tests/test_workspaces_endpoints.py
from httpx import AsyncClient

from tests.conftest import owner_workspace_id


async def test_list_my_workspaces(authed_client, db_session) -> None:
    client, user = authed_client
    ws_id = await owner_workspace_id(db_session, user)
    resp = await client.get("/api/v1/workspaces/mine")
    assert resp.status_code == 200
    body = resp.json()
    assert any(w["id"] == str(ws_id) and w["role"] == "owner" for w in body)


async def test_owner_can_invite(authed_client, db_session) -> None:
    client, user = authed_client
    ws_id = await owner_workspace_id(db_session, user)
    resp = await client.post(
        f"/api/v1/workspaces/{ws_id}/invitations", json={"invited_email": "guest@example.com"}
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["invited_email"] == "guest@example.com"


async def test_non_member_cannot_invite(authed_client, db_session, make_user) -> None:
    client, _ = authed_client
    stranger = await make_user(sub="stranger")
    stranger_ws_id = await owner_workspace_id(db_session, stranger)

    # L'utilisateur authentifie n'est pas membre du workspace de "stranger".
    resp = await client.post(
        f"/api/v1/workspaces/{stranger_ws_id}/invitations", json={"invited_email": "x@example.com"}
    )
    assert resp.status_code == 404


async def test_get_invitation_by_token(authed_client, db_session) -> None:
    client, user = authed_client
    ws_id = await owner_workspace_id(db_session, user)
    created = await client.post(
        f"/api/v1/workspaces/{ws_id}/invitations", json={"invited_email": "guest2@example.com"}
    )
    token = created.json()["token"]
    resp = await client.get(f"/api/v1/invitations/{token}")
    assert resp.status_code == 200
    assert resp.json()["invited_email"] == "guest2@example.com"


async def test_accept_invitation_via_endpoint(authed_client, db_session, db_client) -> None:
    client, user = authed_client
    ws_id = await owner_workspace_id(db_session, user)
    created = await client.post(
        f"/api/v1/workspaces/{ws_id}/invitations", json={"invited_email": "newmember@example.com"}
    )
    token = created.json()["token"]

    register = await db_client.post(
        "/api/v1/auth/register",
        json={"email": "newmember@example.com", "password": "correct horse battery staple", "display_name": "N"},
    )
    assert register.status_code == 201

    resp = await db_client.post(f"/api/v1/invitations/{token}/accept")
    assert resp.status_code == 200

    mine = await db_client.get("/api/v1/workspaces/mine")
    assert any(w["id"] == str(ws_id) for w in mine.json())


async def test_owner_can_remove_member(authed_client, db_session, make_user) -> None:
    client, owner = authed_client
    ws_id = await owner_workspace_id(db_session, owner)
    from app.models.workspace_member import WorkspaceMember
    member_user = await make_user(sub="member-1", email="m1@example.com")
    db_session.add(WorkspaceMember(workspace_id=ws_id, user_id=member_user.id, role="member"))
    await db_session.flush()

    resp = await client.delete(f"/api/v1/workspaces/{ws_id}/members/{member_user.id}")
    assert resp.status_code == 204


async def test_owner_cannot_remove_self(authed_client, db_session) -> None:
    client, owner = authed_client
    ws_id = await owner_workspace_id(db_session, owner)
    resp = await client.delete(f"/api/v1/workspaces/{ws_id}/members/{owner.id}")
    assert resp.status_code == 400
```

(Le test `test_non_member_cannot_invite` illustre l'intention — l'implémenteur doit vérifier que
l'UUID bidon renvoie bien 403/404 selon ce que `owned`-style le endpoint choisit ; ajuster
l'assertion si le comportement réel diffère légèrement, sans changer l'intention du test :
un non-membre ne doit jamais pouvoir inviter dans un workspace qui n'est pas le sien.)

Run: `pytest tests/test_workspaces_endpoints.py -v` — Expected: FAIL (404, routes inexistantes).

- [ ] **Step 2: Implémentation**

```python
# app/api/v1/endpoints/workspaces.py
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, EmailStr

from app.api.deps import CurrentUserDep, EmailSenderDep, SessionDep, SettingsDep
from app.models.workspace import Workspace
from app.models.workspace_member import WorkspaceMember
from app.services.workspace_invites import (
    InvitationEmailMismatch,
    InvitationInvalid,
    accept_invitation,
    create_invitation,
    get_invitation,
)
from app.services.workspaces import is_member
from sqlalchemy import select

router = APIRouter(tags=["workspaces"])


class WorkspaceOut(BaseModel):
    id: UUID
    name: str
    role: str


class InviteRequest(BaseModel):
    invited_email: EmailStr


class InvitationOut(BaseModel):
    id: UUID
    workspace_id: UUID
    invited_email: str
    token: str
    status: str


async def _require_owner(session: SessionDep, workspace_id: UUID, user_id: UUID) -> None:
    row = (
        await session.execute(
            select(WorkspaceMember).where(
                WorkspaceMember.workspace_id == workspace_id, WorkspaceMember.user_id == user_id
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="workspace introuvable")
    if row.role != "owner":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="reserve au proprietaire")


@router.get("/workspaces/mine", response_model=list[WorkspaceOut])
async def list_my_workspaces(user: CurrentUserDep, session: SessionDep) -> list[WorkspaceOut]:
    rows = (
        await session.execute(
            select(Workspace, WorkspaceMember.role)
            .join(WorkspaceMember, WorkspaceMember.workspace_id == Workspace.id)
            .where(WorkspaceMember.user_id == user.id)
        )
    ).all()
    return [WorkspaceOut(id=ws.id, name=ws.name, role=role) for ws, role in rows]


@router.post(
    "/workspaces/{workspace_id}/invitations", response_model=InvitationOut, status_code=status.HTTP_201_CREATED
)
async def invite_to_workspace(
    workspace_id: UUID, body: InviteRequest, user: CurrentUserDep, session: SessionDep,
    email_sender: EmailSenderDep, settings: SettingsDep,
) -> InvitationOut:
    await _require_owner(session, workspace_id, user.id)
    invitation = await create_invitation(
        session, workspace_id=workspace_id, invited_email=body.invited_email, invited_by_user_id=user.id
    )
    await session.commit()
    link = f"{settings.frontend_base_url}/invitations/{invitation.token}"
    await email_sender.send(
        to=body.invited_email, subject="Invitation à rejoindre un espace",
        body_text=f"Tu as ete invite a rejoindre un espace de travail : {link}",
    )
    return InvitationOut(
        id=invitation.id, workspace_id=invitation.workspace_id,
        invited_email=invitation.invited_email, token=invitation.token, status=invitation.status,
    )


@router.get("/invitations/{token}", response_model=InvitationOut)
async def get_invitation_endpoint(token: str, session: SessionDep) -> InvitationOut:
    invitation = await get_invitation(session, token)
    if invitation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="invitation introuvable")
    return InvitationOut(
        id=invitation.id, workspace_id=invitation.workspace_id,
        invited_email=invitation.invited_email, token=invitation.token, status=invitation.status,
    )


@router.post("/invitations/{token}/accept")
async def accept_invitation_endpoint(token: str, user: CurrentUserDep, session: SessionDep) -> dict[str, str]:
    try:
        await accept_invitation(session, token=token, user=user)
    except InvitationEmailMismatch as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from None
    except InvitationInvalid as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from None
    await session.commit()
    return {"status": "ok"}


@router.delete("/workspaces/{workspace_id}/members/{member_user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_member(
    workspace_id: UUID, member_user_id: UUID, user: CurrentUserDep, session: SessionDep
) -> None:
    await _require_owner(session, workspace_id, user.id)
    if member_user_id == user.id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="le proprietaire ne peut pas se retirer")
    row = (
        await session.execute(
            select(WorkspaceMember).where(
                WorkspaceMember.workspace_id == workspace_id, WorkspaceMember.user_id == member_user_id
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="membre introuvable")
    await session.delete(row)
    await session.commit()
```

`app/api/v1/router.py` : ajouter `from app.api.v1.endpoints import workspaces` et
`api_router.include_router(workspaces.router)`.

- [ ] **Step 3: Run + ruff**

```bash
cd backend && export PATH="$PATH:/c/Users/DELL/AppData/Roaming/Python/Python312/Scripts"
.venv/Scripts/python.exe -m pytest tests/test_workspaces_endpoints.py -v
uv run ruff check app/api/v1/endpoints/workspaces.py app/api/v1/router.py tests/test_workspaces_endpoints.py
```
Expected: 7 passed, ruff propre.

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "feat(workspaces): endpoints liste/invitation/acceptation/retrait de membre"
```

---

### Task 10: `GET /websites` élargi à tous les workspaces de l'utilisateur

**Files:**
- Modify: `backend/app/api/v1/endpoints/websites.py`
- Test: `backend/tests/test_websites.py`

**Interfaces:**
- Consumes: `app.services.workspaces.user_workspace_ids` (Task 1).

- [ ] **Step 1: Écrire le test qui échoue**

```python
# tests/test_websites.py — ajouter
async def test_list_websites_includes_sites_from_joined_workspace(
    authed_client, db_session, make_user
) -> None:
    from app.models.website import Website
    from app.models.workspace_member import WorkspaceMember
    from tests.conftest import owner_workspace_id

    client, user = authed_client
    own_ws = await owner_workspace_id(db_session, user)
    db_session.add(Website(workspace_id=own_ws, domain="mine.test", display_name="Mine"))

    other_owner = await make_user(sub="other-owner-ws")
    other_ws = await owner_workspace_id(db_session, other_owner)
    db_session.add(Website(workspace_id=other_ws, domain="shared.test", display_name="Shared"))
    db_session.add(WorkspaceMember(workspace_id=other_ws, user_id=user.id, role="member"))
    await db_session.flush()

    resp = await client.get("/api/v1/websites")
    domains = {w["domain"] for w in resp.json()}
    assert domains == {"mine.test", "shared.test"}
```

Run: `pytest tests/test_websites.py -k joined_workspace -v` — Expected: FAIL (ne renvoie que
`mine.test`, la requête actuelle ne couvre qu'un seul workspace implicite).

- [ ] **Step 2: Implémentation**

Dans `app/api/v1/endpoints/websites.py`, la liste des sites (déjà migrée en Task 1 pour compiler
contre `workspace_id`, mais qui ne couvrait qu'un seul workspace via une jointure directe)
utilise maintenant explicitement :
```python
from app.services.workspaces import user_workspace_ids

@router.get("/websites", response_model=list[WebsiteOut])
async def list_websites(user: CurrentUserDep, session: SessionDep) -> list[Website]:
    ws_ids = await user_workspace_ids(session, user.id)
    return list(
        (
            await session.execute(select(Website).where(Website.workspace_id.in_(ws_ids)))
        ).scalars().all()
    )
```
(adapter au nom réel de la fonction/response_model existants, ne pas dupliquer si Task 1 a déjà
posé une version proche — vérifier l'état du fichier avant d'écrire.)

- [ ] **Step 3: Run + ruff**

```bash
cd backend && export PATH="$PATH:/c/Users/DELL/AppData/Roaming/Python/Python312/Scripts"
.venv/Scripts/python.exe -m pytest tests/test_websites.py -v
uv run ruff check app/api/v1/endpoints/websites.py
```
Expected: tous les tests du fichier passent, ruff propre.

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "feat(websites): GET /websites couvre tous les workspaces de l'utilisateur"
```

---

### Task 11: Frontend — pages login/register + garde d'authentification

**Files:**
- Create: `frontend/app/login/page.tsx`, `frontend/app/register/page.tsx`
- Create: `frontend/lib/api/auth.ts`
- Modify: `frontend/app/(shell)/layout.tsx`

**Interfaces:**
- Produces: `login(email, password)`, `register(email, password, displayName)`,
  `logout()`, `fetchMe()` dans `lib/api/auth.ts`.

- [ ] **Step 1: Client API auth**

```typescript
// frontend/lib/api/auth.ts
import { apiPost, ApiError } from "./client";

export interface MeDto {
  id: string;
  email: string;
  display_name: string | null;
}

export async function login(email: string, password: string): Promise<void> {
  await apiPost("/auth/login", { email, password });
}

export async function register(
  email: string,
  password: string,
  displayName: string,
): Promise<void> {
  await apiPost("/auth/register", { email, password, display_name: displayName });
}

export async function logout(): Promise<void> {
  await apiPost("/auth/logout", undefined);
}

export async function fetchMe(): Promise<MeDto | null> {
  try {
    const { apiGet } = await import("./client");
    return await apiGet<MeDto>("/auth/me");
  } catch (error) {
    if (error instanceof ApiError && error.status === 401) return null;
    throw error;
  }
}
```

- [ ] **Step 2: Page login**

```tsx
// frontend/app/login/page.tsx
"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { toast } from "sonner";

import { login } from "@/lib/api/auth";
import { ApiError } from "@/lib/api/client";

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault();
    setLoading(true);
    try {
      await login(email, password);
      router.push("/overview");
    } catch (error) {
      toast.error(error instanceof ApiError ? error.message : "Connexion impossible");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-canvas px-4">
      <form onSubmit={onSubmit} className="w-full max-w-sm space-y-4 rounded-xl border border-white/[0.08] bg-surface/60 p-6">
        <h1 className="text-lg font-medium text-ink">Se connecter</h1>
        <input
          type="email" required value={email} onChange={(e) => setEmail(e.target.value)}
          placeholder="Email"
          className="h-10 w-full rounded-lg border border-white/[0.08] bg-white/[0.03] px-3 text-sm text-ink"
        />
        <input
          type="password" required value={password} onChange={(e) => setPassword(e.target.value)}
          placeholder="Mot de passe"
          className="h-10 w-full rounded-lg border border-white/[0.08] bg-white/[0.03] px-3 text-sm text-ink"
        />
        <button
          type="submit" disabled={loading}
          className="h-10 w-full rounded-lg bg-zinc-100 text-sm font-medium text-zinc-950 hover:bg-zinc-200 disabled:opacity-60"
        >
          {loading ? "Connexion…" : "Se connecter"}
        </button>
        <a href={`${process.env.NEXT_PUBLIC_API_BASE_URL}/auth/google/start`} className="block text-center text-xs text-ink-muted hover:text-ink">
          Ou continuer avec Google
        </a>
        <a href="/register" className="block text-center text-xs text-ink-muted hover:text-ink">
          Créer un compte
        </a>
      </form>
    </div>
  );
}
```

Note : le lien Google est un `<a href>` classique (navigation plein-navigateur), **pas** un
`fetch` — le flow OAuth exige une redirection réelle du navigateur vers Google, un appel fetch ne
peut pas suivre cette redirection cross-origin. `/auth/google/start` renvoie aujourd'hui un JSON
`{authorization_url}` plutôt qu'une redirection HTTP directe (vérifier le comportement actuel de
l'endpoint dans `auth.py` avant d'écrire ce lien — si c'est bien un JSON, ce lien doit pointer
vers une petite page/route intermédiaire qui fait `fetch` puis `window.location.href =
authorization_url`, pas un `<a href>` direct vers l'endpoint API).

- [ ] **Step 3: Page register (même structure que login, formulaire `email/password/displayName`
  → `register()` → `router.push("/overview")`)**

Reprendre exactement la structure du Step 2 en remplaçant `login` par `register` et en ajoutant
un champ `displayName`.

- [ ] **Step 4: Garde d'authentification dans le layout shell**

```tsx
// app/(shell)/layout.tsx — ajouter avant le rendu du shell
import { redirect } from "next/navigation";
import { fetchMe } from "@/lib/api/auth";
// ... imports existants inchangés

export default async function ShellLayout({ children }: LayoutProps<"/">) {
  const me = await fetchMe();
  if (me === null) redirect("/login");
  // ... reste du layout inchange (cookies, ShellProvider, etc.)
}
```

Attention : `fetchMe()` utilise `apiGet` qui appelle `fetch` sans transmettre les cookies de la
requête serveur entrante — en Server Component, il faut transmettre le cookie de session
manuellement via l'en-tête `Cookie` (lire `cookies()` de `next/headers` et le passer à `fetch`).
Adapter `fetchMe` pour accepter un cookie optionnel, ou créer une variante serveur dédiée
`fetchMeServer(cookieHeader: string)` qui fait l'appel avec cet en-tête explicite plutôt que
`credentials: "include"` (qui ne s'applique qu'aux requêtes émises par le navigateur).

- [ ] **Step 5: Vérifier build + lint**

```bash
cd frontend
npm run build
npm run lint
```
Expected: 0 erreur, 0 warning.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "feat(frontend): pages login/register + garde d'authentification sur le shell"
```

---

### Task 12: Frontend — page d'acceptation d'invitation

**Files:**
- Create: `frontend/app/invitations/[token]/page.tsx`
- Modify: `frontend/lib/api/auth.ts` (ou nouveau `lib/api/invitations.ts`)

**Interfaces:**
- Produces: `getInvitation(token)`, `acceptInvitation(token)`.

- [ ] **Step 1: Client API**

```typescript
// frontend/lib/api/invitations.ts
import { apiGet, apiPost } from "./client";

export interface InvitationDto {
  id: string;
  workspace_id: string;
  invited_email: string;
  token: string;
  status: string;
}

export async function getInvitation(token: string): Promise<InvitationDto> {
  return apiGet<InvitationDto>(`/invitations/${token}`);
}

export async function acceptInvitation(token: string): Promise<void> {
  await apiPost(`/invitations/${token}/accept`, undefined);
}
```

- [ ] **Step 2: Page**

```tsx
// frontend/app/invitations/[token]/page.tsx
"use client";

import { use, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { toast } from "sonner";

import { acceptInvitation, getInvitation, type InvitationDto } from "@/lib/api/invitations";
import { fetchMe } from "@/lib/api/auth";
import { ApiError } from "@/lib/api/client";

export default function InvitationPage({ params }: { params: Promise<{ token: string }> }) {
  const { token } = use(params);
  const router = useRouter();
  const [invitation, setInvitation] = useState<InvitationDto | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    void getInvitation(token)
      .then(setInvitation)
      .catch(() => setError("Invitation introuvable ou expirée."));
  }, [token]);

  async function onAccept() {
    try {
      const me = await fetchMe();
      if (me === null) {
        router.push(`/register?invitation=${token}`);
        return;
      }
      await acceptInvitation(token);
      toast.success("Tu as rejoint l'espace.");
      router.push("/overview");
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Impossible d'accepter l'invitation");
    }
  }

  if (error) return <p className="p-8 text-sm text-ink-muted">{error}</p>;
  if (!invitation) return <p className="p-8 text-sm text-ink-muted">Chargement…</p>;

  return (
    <div className="flex min-h-screen items-center justify-center bg-canvas px-4">
      <div className="w-full max-w-sm space-y-4 rounded-xl border border-white/[0.08] bg-surface/60 p-6 text-center">
        <p className="text-sm text-ink">
          Tu es invité à rejoindre un espace de travail ({invitation.invited_email}).
        </p>
        <button
          type="button" onClick={() => void onAccept()}
          className="h-10 w-full rounded-lg bg-zinc-100 text-sm font-medium text-zinc-950 hover:bg-zinc-200"
        >
          Rejoindre
        </button>
      </div>
    </div>
  );
}
```

Note : le flow "invité pas encore inscrit" (`router.push` vers `/register?invitation=${token}`)
suppose que la page register, une fois le compte créé, renvoie automatiquement vers cette même
page d'invitation pour finaliser l'acceptation plutôt que vers `/overview` — ajuster
`register/page.tsx` (Task 11) pour lire un éventuel query param `invitation` et rediriger vers
`/invitations/{invitation}` au lieu de `/overview` quand il est présent.

- [ ] **Step 3: Vérifier build + lint**

```bash
cd frontend
npm run build
npm run lint
```
Expected: 0 erreur, 0 warning.

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "feat(frontend): page d'acceptation d'invitation a un workspace"
```

---

### Task 13: Vérification finale

**Files:** aucun changement de code — vérification uniquement.

- [ ] **Step 1: Suite backend complète, deux fois (détection de flake)**

```bash
cd backend && export PATH="$PATH:/c/Users/DELL/AppData/Roaming/Python/Python312/Scripts"
.venv/Scripts/python.exe -m pytest -W error -q
.venv/Scripts/python.exe -m pytest -W error -q
uv run ruff check app tests
uv run alembic check
```
Expected : même nombre de tests verts sur les deux runs, 0 erreur ruff, `alembic check` propre.

- [ ] **Step 2: Frontend**

```bash
cd frontend
npm run build
npm run lint
```
Expected: 0/0.

- [ ] **Step 3: Smoke test manuel (navigateur, backend + frontend démarrés)**

1. Aller sur `/login` sans session → formulaire affiché (pas de redirection en boucle).
2. `/register` avec un nouvel email → redirection `/overview`, un workspace existe (vérifier via
   `GET /api/v1/workspaces/mine` dans les devtools réseau).
3. Depuis ce compte, appeler `POST /api/v1/workspaces/{id}/invitations` (via un outil comme
   `curl` avec le cookie de session, ou une UI temporaire) avec un second email → vérifier dans
   les logs backend (`ConsoleEmailSender` → `logger.info`) que le lien d'invitation apparaît.
4. Ouvrir ce lien dans une session non connectée → page d'invitation affichée → créer un compte
   avec l'email invité → membre ajouté au workspace (vérifier `GET /workspaces/mine` renvoie les
   deux workspaces pour l'inviteur si applicable, un seul pour l'invité incluant celui partagé).
5. `POST /auth/logout` → `GET /auth/me` renvoie 401.

- [ ] **Step 4: Rapport**

Résumer à l'utilisateur : nombre de tests, résultat build/lint, résultat du smoke test manuel,
rappel explicite que l'incrément B (connexion Google pour GA4/GSC + UI `/connections`) reste à
planifier séparément, et que GitHub OAuth + fournisseur d'email réel restent hors périmètre.
