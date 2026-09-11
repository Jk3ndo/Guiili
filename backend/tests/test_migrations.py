import os
import subprocess
import sys
from pathlib import Path

import pytest_asyncio
from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import get_settings

BACKEND_DIR = Path(__file__).resolve().parents[1]
MIG_URL = get_settings().database_url_migrations_test
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
