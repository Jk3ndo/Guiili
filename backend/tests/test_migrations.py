import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest_asyncio
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import get_settings
from tests.db_safety import assert_safe_test_database

BACKEND_DIR = Path(__file__).resolve().parents[1]
MIG_URL = get_settings().database_url_migrations_test
assert_safe_test_database(
    "DATABASE_URL_MIGRATIONS_TEST", MIG_URL, get_settings().database_url
)
EXPECTED_TABLES = {
    "users",
    "google_connections",
    "websites",
    "website_google_links",
    "audit_snapshots",
    "issue_items",
    "audit_log",
    "oauth_states",
    "advisor_threads",
    "advisor_messages",
    "advisor_usage",
    "advisor_tool_calls",
    "user_advisor_settings",
    "website_profiles",
    "measurement_item_statuses",
    "measurement_item_events",
    "metric_points",
    "metric_rollups",
    "schedules",
    "job_runs",
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
        check=False,
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


async def test_metric_points_is_partitioned_by_month_with_a_default(
    clean_migrations_db,
) -> None:
    assert _alembic("upgrade", "head").returncode == 0
    engine = create_async_engine(MIG_URL)
    try:
        async with engine.connect() as conn:
            strategy = await conn.scalar(
                text(
                    "SELECT p.partstrat::text FROM pg_partitioned_table p "
                    "JOIN pg_class c ON c.oid = p.partrelid WHERE c.relname = 'metric_points'"
                )
            )
            children = set(
                (
                    await conn.execute(
                        text(
                            "SELECT c.relname FROM pg_inherits i "
                            "JOIN pg_class c ON c.oid = i.inhrelid "
                            "JOIN pg_class p ON p.oid = i.inhparent "
                            "WHERE p.relname = 'metric_points'"
                        )
                    )
                ).scalars()
            )
    finally:
        await engine.dispose()
    assert strategy == "r"  # RANGE
    assert "metric_points_default" in children
    assert f"metric_points_p{datetime.now(UTC):%Y_%m}" in children
    assert len(children) == 9  # partition par défaut + M-4 .. M+3
