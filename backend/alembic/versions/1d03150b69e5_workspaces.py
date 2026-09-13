"""workspaces

Revision ID: 1d03150b69e5
Revises: f1572fec5930
Create Date: 2026-09-12 08:18:17.000277

"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '1d03150b69e5'
down_revision: str | Sequence[str] | None = 'f1572fec5930'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "workspaces",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("owner_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"], name=op.f("fk_workspaces_owner_user_id_users"), ondelete="RESTRICT"),
    )
    op.create_index("ix_workspaces_owner_user_id", "workspaces", ["owner_user_id"])

    op.create_table(
        "workspace_members",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("joined_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], name=op.f("fk_workspace_members_workspace_id_workspaces"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_workspace_members_user_id_users"), ondelete="CASCADE"),
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
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], name=op.f("fk_workspace_invitations_workspace_id_workspaces"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["invited_by_user_id"], ["users.id"], name=op.f("fk_workspace_invitations_invited_by_user_id_users"), ondelete="CASCADE"),
    )
    op.create_index("ix_workspace_invitations_workspace_id", "workspace_invitations", ["workspace_id"])
    op.create_index(
        "ix_workspace_invitations_token", "workspace_invitations", ["token"], unique=True
    )

    op.create_table(
        "password_reset_tokens",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("token", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_password_reset_tokens_user_id_users"), ondelete="CASCADE"),
    )
    op.create_index("ix_password_reset_tokens_user_id", "password_reset_tokens", ["user_id"])
    op.create_index(
        "ix_password_reset_tokens_token", "password_reset_tokens", ["token"], unique=True
    )

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

    # google_connections : PAS la meme mecanique que websites/advisor_usage
    # ci-dessus — un backfill naif casserait le chiffrement des jetons.
    # `connection_aad(workspace_id, google_sub)` (app/services/connections.py)
    # lie cryptographiquement le blob AES-GCM au couple (workspace_id, sub) via
    # l'AAD. Avant cette migration, chaque `refresh_token_encrypted` a ete
    # chiffre avec l'ancien `user_id` de la ligne dans cette AAD. Le backfill
    # ci-dessous assigne `workspace_id` = id du NOUVEAU workspace cree plus
    # haut (lui-meme un gen_random_uuid() frais, sans aucun lien avec l'ancien
    # user_id) : `decrypt_refresh_token` recalculerait alors une AAD differente
    # de celle utilisee au chiffrement -> `TokenDecryptionError` permanent pour
    # CHAQUE ligne preexistante. Il n'existe aucune facon legitime de preserver
    # ces jetons (le lien cryptographique a l'ancienne cle est irrecuperable) :
    # on supprime donc TOUTES les lignes qui existent avant ce backfill, avant
    # meme d'ajouter la colonne — il n'y a alors plus rien a backfiller ni
    # d'ordre a respecter. Ne pas "reparer" ceci en tentant de represerver ces
    # lignes : c'est le point precis de ce commentaire.
    conn.execute(sa.text("DELETE FROM google_connections"))

    op.add_column("google_connections", sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=True))
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
    op.drop_constraint("pk_advisor_usage", "advisor_usage", type_="primary")
    op.drop_column("advisor_usage", "user_id")
    op.create_primary_key("pk_advisor_usage", "advisor_usage", ["workspace_id", "day"])

    # oauth_states : + workspace_id (nullable, increment B)
    op.add_column("oauth_states", sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key(
        "fk_oauth_states_workspace_id_workspaces", "oauth_states", "workspaces", ["workspace_id"], ["id"], ondelete="CASCADE"
    )
    op.create_foreign_key(
        "fk_websites_workspace_id_workspaces", "websites", "workspaces", ["workspace_id"], ["id"], ondelete="CASCADE"
    )
    op.create_foreign_key(
        "fk_google_connections_workspace_id_workspaces", "google_connections", "workspaces", ["workspace_id"], ["id"], ondelete="CASCADE"
    )
    op.create_foreign_key(
        "fk_advisor_usage_workspace_id_workspaces", "advisor_usage", "workspaces", ["workspace_id"], ["id"], ondelete="CASCADE"
    )


def downgrade() -> None:
    """Downgrade schema."""
    conn = op.get_bind()

    # oauth_states : retirer la colonne ajoutee (jamais exploitee avant l'increment B).
    op.drop_constraint("fk_oauth_states_workspace_id_workspaces", "oauth_states", type_="foreignkey")
    op.drop_column("oauth_states", "workspace_id")

    # advisor_usage : workspace_id -> user_id (backfill via owner_user_id du workspace).
    op.drop_constraint("fk_advisor_usage_workspace_id_workspaces", "advisor_usage", type_="foreignkey")
    op.add_column("advisor_usage", sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True))
    conn.execute(
        sa.text(
            "UPDATE advisor_usage au SET user_id = w.owner_user_id "
            "FROM workspaces w WHERE w.id = au.workspace_id"
        )
    )
    op.alter_column("advisor_usage", "user_id", nullable=False)
    op.drop_constraint("pk_advisor_usage", "advisor_usage", type_="primary")
    op.drop_column("advisor_usage", "workspace_id")
    op.create_primary_key("pk_advisor_usage", "advisor_usage", ["user_id", "day"])

    # google_connections : workspace_id -> user_id.
    op.drop_constraint("fk_google_connections_workspace_id_workspaces", "google_connections", type_="foreignkey")
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
    op.drop_constraint("fk_websites_workspace_id_workspaces", "websites", type_="foreignkey")
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
