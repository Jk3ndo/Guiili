"""measurement plan tables

Revision ID: 8f2a6c41d7b3
Revises: 1d03150b69e5
Create Date: 2026-09-24 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "8f2a6c41d7b3"
down_revision: str | Sequence[str] | None = "1d03150b69e5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "website_profiles",
        sa.Column("website_id", sa.Uuid(), nullable=False),
        sa.Column("detected_types", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("confirmed_types", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("params", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("headless_result", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("headless_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["website_id"],
            ["websites.id"],
            name=op.f("fk_website_profiles_website_id_websites"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("website_id", name=op.f("pk_website_profiles")),
    )
    op.create_table(
        "measurement_item_statuses",
        sa.Column("website_id", sa.Uuid(), nullable=False),
        sa.Column("item_id", sa.String(length=64), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("evidence", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("reason", sa.String(length=64), nullable=True),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("dismissed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["website_id"],
            ["websites.id"],
            name=op.f("fk_measurement_item_statuses_website_id_websites"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "website_id", "item_id", name=op.f("pk_measurement_item_statuses")
        ),
    )
    op.create_table(
        "measurement_item_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("website_id", sa.Uuid(), nullable=False),
        sa.Column("item_id", sa.String(length=64), nullable=False),
        sa.Column("from_state", sa.String(length=32), nullable=True),
        sa.Column("to_state", sa.String(length=32), nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("evidence", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.ForeignKeyConstraint(
            ["website_id"],
            ["websites.id"],
            name=op.f("fk_measurement_item_events_website_id_websites"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_measurement_item_events")),
    )
    op.create_index(
        "ix_measurement_item_events_site_item_at",
        "measurement_item_events",
        ["website_id", "item_id", "at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_measurement_item_events_site_item_at", table_name="measurement_item_events"
    )
    op.drop_table("measurement_item_events")
    op.drop_table("measurement_item_statuses")
    op.drop_table("website_profiles")
