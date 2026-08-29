import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import ConnectionStatus
from app.models.google_connection import GoogleConnection
from app.models.user import User


async def _make_user(session: AsyncSession, sub: str = "sub-1") -> User:
    user = User(email=f"{sub}@example.com", google_sub=sub)
    session.add(user)
    await session.flush()
    return user


async def test_user_defaults(db_session: AsyncSession) -> None:
    user = await _make_user(db_session)
    assert user.auth_provider == "google"
    assert user.id is not None
    assert user.created_at is not None


async def test_connection_status_defaults_active(db_session: AsyncSession) -> None:
    user = await _make_user(db_session)
    conn = GoogleConnection(
        user_id=user.id,
        google_account_email="acct@example.com",
        google_sub="g-sub-1",
        granted_scopes=["openid", "email"],
        refresh_token_encrypted=b"\x00\x01",
        encryption_key_version=1,
    )
    db_session.add(conn)
    await db_session.flush()
    assert conn.status == ConnectionStatus.ACTIVE


async def test_connection_unique_user_google_sub(db_session: AsyncSession) -> None:
    user = await _make_user(db_session)
    common = {
        "user_id": user.id,
        "google_account_email": "a@example.com",
        "google_sub": "dup-sub",
        "granted_scopes": ["openid"],
        "refresh_token_encrypted": b"x",
        "encryption_key_version": 1,
    }
    db_session.add(GoogleConnection(**common))
    await db_session.flush()
    db_session.add(GoogleConnection(**common))
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_user_cascade_deletes_connections(db_session: AsyncSession) -> None:
    user = await _make_user(db_session)
    db_session.add(
        GoogleConnection(
            user_id=user.id,
            google_account_email="a@example.com",
            google_sub="c-sub",
            granted_scopes=["openid"],
            refresh_token_encrypted=b"x",
            encryption_key_version=1,
        )
    )
    await db_session.flush()
    await db_session.delete(user)
    await db_session.flush()
    remaining = (await db_session.execute(select(GoogleConnection))).scalars().all()
    assert remaining == []
