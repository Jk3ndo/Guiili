"""Enum CHECK ↔ Python enum mapping guard (PARTIAL).

alembic/env.py disables the `checkconstraint_byname` autogenerate comparator,
so `alembic check` cannot notice CHECK-constraint drift.

Scope of THIS test: it reads each ck_* enum CHECK from a database built by
`create_all()` (the `engine` fixture) and asserts its string literals equal
{m.value for m in EnumClass}. Because both sides derive from the same model
definitions, it catches a `pg_enum`/`values_callable` regression (the "ACTIVE"
vs "active" bug) — NOT a stale migration. Adding an enum member without
regenerating the migration keeps this test (and the whole suite) green.

A real migration-freshness guard would run these assertions against
`database_url_migrations_test` after `alembic upgrade head` (reuse the
`clean_migrations_db` machinery in test_migrations.py). Deferred to the OAuth
spec — see the ledger.
"""

import re

import pytest
from sqlalchemy import text

from app.models.enums import (
    AuditResult,
    ConnectionStatus,
    IssueCategory,
    IssueSeverity,
    IssueStatus,
    ResourceType,
    SnapshotSource,
)

# (table, ck_ constraint name, enum class)
ENUM_CHECKS = [
    ("google_connections", "ck_google_connections_connection_status", ConnectionStatus),
    ("website_google_links", "ck_website_google_links_resource_type", ResourceType),
    ("audit_snapshots", "ck_audit_snapshots_snapshot_source", SnapshotSource),
    ("issue_items", "ck_issue_items_issue_category", IssueCategory),
    ("issue_items", "ck_issue_items_issue_severity", IssueSeverity),
    ("issue_items", "ck_issue_items_issue_status", IssueStatus),
    ("audit_log", "ck_audit_log_audit_result", AuditResult),
]

_CONSTRAINTDEF_SQL = text(
    """
    SELECT pg_get_constraintdef(con.oid)
    FROM pg_constraint con
    JOIN pg_class rel ON rel.oid = con.conrelid
    WHERE con.contype = 'c'
      AND rel.relname = :table
      AND con.conname = :name
    """
)


@pytest.mark.parametrize(
    ("table", "constraint_name", "enum_cls"),
    ENUM_CHECKS,
    ids=[name for _, name, _ in ENUM_CHECKS],
)
async def test_enum_check_matches_python_values(
    engine, table: str, constraint_name: str, enum_cls: type
) -> None:
    async with engine.connect() as conn:
        row = (
            await conn.execute(
                _CONSTRAINTDEF_SQL, {"table": table, "name": constraint_name}
            )
        ).first()

    assert row is not None, f"CHECK {constraint_name} introuvable sur {table}"
    literals = set(re.findall(r"'([^']*)'", row[0]))
    assert literals == {m.value for m in enum_cls}
