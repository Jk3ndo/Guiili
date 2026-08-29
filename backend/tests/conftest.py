from collections.abc import AsyncGenerator

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import app.models  # import à effet de bord : enregistre les modèles dans Base.metadata
from app.config import get_settings
from app.db.base import Base
from app.db.session import build_engine, get_session
from app.main import app


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def engine() -> AsyncGenerator:
    eng = build_engine(get_settings().database_url_test)
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await eng.dispose()


@pytest_asyncio.fixture
async def db_session(engine) -> AsyncGenerator[AsyncSession, None]:
    conn = await engine.connect()
    trans = await conn.begin()
    # join_transaction_mode="create_savepoint": the session runs inside a
    # SAVEPOINT, so a test that triggers an IntegrityError rolls back to the
    # savepoint instead of poisoning the outer transaction. The teardown
    # trans.rollback() below then stays clean (no "transaction already
    # deassociated from connection" SAWarning).
    session_maker = async_sessionmaker(
        bind=conn,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )
    session = session_maker()
    try:
        yield session
    finally:
        await session.close()
        await trans.rollback()
        await conn.close()


@pytest_asyncio.fixture
async def client() -> AsyncGenerator[AsyncClient, None]:
    """HTTP client on the app with NO DB dependency override — for routes that
    don't touch Postgres (e.g. /health)."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest_asyncio.fixture
async def db_client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """HTTP client whose get_session dependency is bound to the test
    transaction-scoped db_session."""

    async def _override_get_session() -> AsyncGenerator[AsyncSession, None]:
        yield db_session

    app.dependency_overrides[get_session] = _override_get_session
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.pop(get_session, None)
