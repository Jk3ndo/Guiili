"""Enum CHECK ↔ Python enum mapping guard.

alembic/env.py disables the `checkconstraint_byname` autogenerate comparator,
so `alembic check` cannot notice CHECK-constraint drift.

Two layers here:

1. `test_enum_check_matches_python_values` — reads each ck_* enum CHECK from a
   database built by `create_all()` (the `engine` fixture). Both sides derive
   from the same model definitions, so it catches a `pg_enum`/`values_callable`
   regression (the "ACTIVE" vs "active" bug) — NOT a stale migration.

2. `test_enum_check_matches_after_migration` — the real freshness guard: runs
   the SAME assertions against `database_url_migrations_test` AFTER
   `alembic upgrade head` (reuses `clean_migrations_db` from test_migrations.py).
   Adding an enum member without regenerating the migration now fails here.
"""

import re

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import get_settings
from app.models.enums import (
    AuditResult,
    ConnectionStatus,
    IssueCategory,
    IssueSeverity,
    IssueStatus,
    ResourceType,
    SnapshotSource,
    StackKind,
)
from tests.test_migrations import _alembic

_MIG_URL = get_settings().database_url_migrations_test

# (table, ck_ constraint name, enum class)
ENUM_CHECKS = [
    ("google_connections", "ck_google_connections_connection_status", ConnectionStatus),
    ("website_google_links", "ck_website_google_links_resource_type", ResourceType),
    ("audit_snapshots", "ck_audit_snapshots_snapshot_source", SnapshotSource),
    ("issue_items", "ck_issue_items_issue_category", IssueCategory),
    ("issue_items", "ck_issue_items_issue_severity", IssueSeverity),
    ("issue_items", "ck_issue_items_issue_status", IssueStatus),
    ("audit_log", "ck_audit_log_audit_result", AuditResult),
    ("websites", "ck_websites_stack_kind", StackKind),
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
            await conn.execute(_CONSTRAINTDEF_SQL, {"table": table, "name": constraint_name})
        ).first()

    assert row is not None, f"CHECK {constraint_name} introuvable sur {table}"
    literals = set(re.findall(r"'([^']*)'", row[0]))
    assert literals == {m.value for m in enum_cls}


@pytest.fixture(scope="module")
def migrated_head_db():
    """Un SEUL `alembic upgrade head` pour les 8 assertions d'enum.

    L'ancienne version relançait toute la migration (downgrade + upgrade +
    downgrade) une fois par parametre — 24 sous-processus alembic ouvrant
    chacun une connexion a la base de migration. Sous charge (suite complete)
    cette rafale saturait les slots Postgres et un `upgrade` timeoutait
    (flake `TimeoutError` d'asyncpg). Une seule montee, en fixture de module,
    supprime la rafale.
    """
    _alembic("downgrade", "base")
    result = _alembic("upgrade", "head")
    assert result.returncode == 0, result.stderr
    yield
    _alembic("downgrade", "base")


@pytest.mark.parametrize(
    ("table", "constraint_name", "enum_cls"),
    ENUM_CHECKS,
    ids=[name for _, name, _ in ENUM_CHECKS],
)
async def test_enum_check_matches_after_migration(
    migrated_head_db,
    table: str,
    constraint_name: str,
    enum_cls: type,
) -> None:
    """Garde-fou de fraicheur : la CHECK EN BASE (posee par la migration) doit
    correspondre a l'enum Python. Ajouter un membre sans migrer echoue ici."""
    mig_engine = create_async_engine(_MIG_URL)
    try:
        async with mig_engine.connect() as conn:
            row = (
                await conn.execute(_CONSTRAINTDEF_SQL, {"table": table, "name": constraint_name})
            ).first()
    finally:
        await mig_engine.dispose()

    assert row is not None, f"CHECK {constraint_name} absente apres migration"
    literals = set(re.findall(r"'([^']*)'", row[0]))
    assert literals == {m.value for m in enum_cls}, (
        f"{constraint_name} en base != enum {enum_cls.__name__} — migration perimee ?"
    )
