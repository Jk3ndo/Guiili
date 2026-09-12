from collections.abc import AsyncGenerator, Awaitable, Callable
from uuid import UUID

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import app.models  # import à effet de bord : enregistre les modèles dans Base.metadata
from app.config import get_settings
from app.db.base import Base
from app.db.session import build_engine, get_session
from app.main import app
from app.models.user import User
from app.models.workspace import Workspace
from app.models.workspace_member import WorkspaceMember
from app.security.session import issue_session


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


UserFactory = Callable[..., Awaitable[User]]


@pytest_asyncio.fixture
async def make_user(db_session: AsyncSession) -> UserFactory:
    """Crée un utilisateur dans la transaction de test."""

    async def _make(*, sub: str = "sub-user", email: str | None = None,
                    name: str | None = None) -> User:
        user = User(
            email=email or f"{sub}@example.com", google_sub=sub, display_name=name
        )
        db_session.add(user)
        await db_session.flush()
        workspace = Workspace(name=user.display_name or user.email, owner_user_id=user.id)
        db_session.add(workspace)
        await db_session.flush()
        db_session.add(
            WorkspaceMember(workspace_id=workspace.id, user_id=user.id, role="owner")
        )
        await db_session.flush()
        return user

    return _make


async def owner_workspace_id(session: AsyncSession, user: User) -> UUID:
    """Workspace dont `user` est owner — cree transparemment par make_user ci-dessus.
    Fonction ordinaire (pas une fixture) : importable et appelable depuis n'importe
    quel fichier de test avec `from tests.conftest import owner_workspace_id`."""
    return (
        await session.execute(
            select(WorkspaceMember.workspace_id).where(
                WorkspaceMember.user_id == user.id, WorkspaceMember.role == "owner"
            )
        )
    ).scalar_one()


@pytest_asyncio.fixture
async def authed_client(
    db_client: AsyncClient, make_user: UserFactory
) -> tuple[AsyncClient, User]:
    """Client HTTP + cookie de session signé pour un utilisateur frais."""
    user = await make_user(sub="owner-sub", email="owner@example.com", name="Owner")
    settings = get_settings()
    db_client.cookies.set(
        settings.session_cookie_name,
        issue_session(user.id, secret=settings.app_secret_key.get_secret_value()),
    )
    return db_client, user
