"""website_stack_label_ssl_archive + react/vite/php dans stack_kind

Revision ID: 0c6d572e41fe
Revises: d24c2a97270e
Create Date: 2026-09-03 12:01:03.330356

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0c6d572e41fe"
down_revision: str | Sequence[str] | None = "d24c2a97270e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD_VALUES = ("nextjs", "wordpress", "woocommerce", "nuxt", "vue", "angular", "generic", "unknown")
_NEW_VALUES = (*_OLD_VALUES[:6], "react", "vite", "php", "generic", "unknown")


def _recreate_check(values: Sequence[str]) -> None:
    # `alembic/env.py` desactive le comparateur checkconstraint_byname : on pilote
    # la CHECK d'enum en SQL brut (le nom exact evite la convention de nommage
    # alembic qui prefixerait `ck_websites_` une seconde fois).
    joined = ", ".join(f"'{value}'" for value in values)
    op.execute("ALTER TABLE websites DROP CONSTRAINT ck_websites_stack_kind")
    op.execute(
        f"ALTER TABLE websites ADD CONSTRAINT ck_websites_stack_kind "
        f"CHECK (detected_stack IN ({joined}))"
    )


def upgrade() -> None:
    op.add_column("websites", sa.Column("stack_label", sa.String(length=100), nullable=True))
    op.add_column(
        "websites",
        sa.Column(
            "allow_insecure_probe",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column("websites", sa.Column("ssl_status", sa.String(length=32), nullable=True))
    op.add_column(
        "websites", sa.Column("ssl_expires_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "websites", sa.Column("ssl_checked_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("websites", sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True))

    _recreate_check(_NEW_VALUES)


def downgrade() -> None:
    op.execute(
        "UPDATE websites SET detected_stack = 'unknown' "
        "WHERE detected_stack IN ('react', 'vite', 'php')"
    )
    _recreate_check(_OLD_VALUES)

    op.drop_column("websites", "archived_at")
    op.drop_column("websites", "ssl_checked_at")
    op.drop_column("websites", "ssl_expires_at")
    op.drop_column("websites", "ssl_status")
    op.drop_column("websites", "allow_insecure_probe")
    op.drop_column("websites", "stack_label")
