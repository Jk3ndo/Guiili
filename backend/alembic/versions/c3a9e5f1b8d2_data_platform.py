"""lot B : metric_points (partitionnée par mois), metric_rollups, schedules, job_runs

Revision ID: c3a9e5f1b8d2
Revises: 8f2a6c41d7b3
Create Date: 2026-09-26 12:00:00.000000

"""

from collections.abc import Sequence
from datetime import UTC, date, datetime

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c3a9e5f1b8d2"
down_revision: str | Sequence[str] | None = "8f2a6c41d7b3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Mois créés d'avance : 4 mois passés (le rattrapage initial couvre 90 jours) et 3 à
# venir. Les suivants sont créés par la tâche planifiée `partition_maintenance`.
_MONTHS_BACK = 4
_MONTHS_AHEAD = 3


def _add_months(month: date, count: int) -> date:
    index = month.year * 12 + (month.month - 1) + count
    return date(index // 12, index % 12 + 1, 1)


def upgrade() -> None:
    op.create_table(
        "metric_points",
        sa.Column("website_id", sa.Uuid(), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("metric", sa.String(length=64), nullable=False),
        sa.Column("dim_key", sa.String(length=64), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("value", sa.Double(), nullable=False),
        sa.Column("dims", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("collected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=True),
        sa.ForeignKeyConstraint(
            ["website_id"],
            ["websites.id"],
            name=op.f("fk_metric_points_website_id_websites"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "website_id", "source", "metric", "dim_key", "day", name=op.f("pk_metric_points")
        ),
        postgresql_partition_by="RANGE (day)",
    )
    op.execute("CREATE TABLE metric_points_default PARTITION OF metric_points DEFAULT")
    current = datetime.now(UTC).date().replace(day=1)
    for offset in range(-_MONTHS_BACK, _MONTHS_AHEAD + 1):
        start = _add_months(current, offset)
        end = _add_months(start, 1)
        op.execute(
            f"CREATE TABLE metric_points_p{start:%Y_%m} PARTITION OF metric_points "
            f"FOR VALUES FROM ('{start.isoformat()}') TO ('{end.isoformat()}')"
        )

    op.create_table(
        "metric_rollups",
        sa.Column("website_id", sa.Uuid(), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("metric", sa.String(length=64), nullable=False),
        sa.Column("dim_key", sa.String(length=64), nullable=False),
        sa.Column("grain", sa.String(length=8), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("value", sa.Double(), nullable=False),
        sa.Column("days_covered", sa.Integer(), nullable=False),
        sa.Column("dims", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["website_id"],
            ["websites.id"],
            name=op.f("fk_metric_rollups_website_id_websites"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "website_id",
            "source",
            "metric",
            "dim_key",
            "grain",
            "period_start",
            name=op.f("pk_metric_rollups"),
        ),
    )

    op.create_table(
        "schedules",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("website_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=40), nullable=False),
        sa.Column("frequency", sa.String(length=16), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("next_due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_status", sa.String(length=16), nullable=True),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failing_since", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_code", sa.String(length=64), nullable=True),
        sa.Column("backfill_done_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["website_id"],
            ["websites.id"],
            name=op.f("fk_schedules_website_id_websites"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_schedules")),
        sa.UniqueConstraint("website_id", "kind", name="uq_schedules_website_kind"),
    )
    op.create_index("ix_schedules_next_due_at", "schedules", ["next_due_at"])

    op.create_table(
        "job_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=200), nullable=False),
        sa.Column("kind", sa.String(length=40), nullable=False),
        sa.Column("website_id", sa.Uuid(), nullable=True),
        sa.Column("workspace_id", sa.Uuid(), nullable=True),
        sa.Column("window_label", sa.String(length=40), nullable=False),
        sa.Column("params", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "enqueued_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_detail", sa.String(length=300), nullable=True),
        sa.Column("recoverable", sa.Boolean(), nullable=True),
        sa.Column("observations", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["website_id"],
            ["websites.id"],
            name=op.f("fk_job_runs_website_id_websites"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_job_runs_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_job_runs")),
        sa.UniqueConstraint("idempotency_key", name="uq_job_runs_idempotency_key"),
    )
    op.create_index("ix_job_runs_status_lease", "job_runs", ["status", "lease_expires_at"])
    op.create_index("ix_job_runs_workspace_enqueued", "job_runs", ["workspace_id", "enqueued_at"])
    op.create_index(
        "ix_job_runs_website_kind_enqueued", "job_runs", ["website_id", "kind", "enqueued_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_job_runs_website_kind_enqueued", table_name="job_runs")
    op.drop_index("ix_job_runs_workspace_enqueued", table_name="job_runs")
    op.drop_index("ix_job_runs_status_lease", table_name="job_runs")
    op.drop_table("job_runs")
    op.drop_index("ix_schedules_next_due_at", table_name="schedules")
    op.drop_table("schedules")
    op.drop_table("metric_rollups")
    # Supprimer la table partitionnée supprime aussi toutes ses partitions.
    op.drop_table("metric_points")
