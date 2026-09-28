"""lot B : source_quota_events (historique en ajout seul du disjoncteur de quota)

Revision ID: a7d41c9e2b56
Revises: c3a9e5f1b8d2
Create Date: 2026-09-27 10:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a7d41c9e2b56"
down_revision: str | Sequence[str] | None = "c3a9e5f1b8d2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "source_quota_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_source_quota_events_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_source_quota_events")),
    )
    op.create_index(
        "ix_source_quota_events_workspace_source_at",
        "source_quota_events",
        ["workspace_id", "source", "at"],
    )


def downgrade() -> None:
    op.drop_index("ix_source_quota_events_workspace_source_at", table_name="source_quota_events")
    op.drop_table("source_quota_events")
