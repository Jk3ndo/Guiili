from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import get_settings


def build_engine(url: str) -> AsyncEngine:
    # `hide_parameters` : une erreur de base (contrainte, type) embarque sinon
    # `[parameters: (...)]` avec les valeurs brutes dans son message, donc dans les logs.
    return create_async_engine(url, pool_pre_ping=True, hide_parameters=True)


engine: AsyncEngine = build_engine(get_settings().database_url)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session
