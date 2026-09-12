import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import ConnectionStatus
from app.models.google_connection import GoogleConnection
from app.models.user import User
from app.models.workspace import Workspace
from tests.conftest import owner_workspace_id


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


async def test_connection_status_defaults_active(
    db_session: AsyncSession, make_user
) -> None:
    user = await make_user(sub="sub-1")
    workspace_id = await owner_workspace_id(db_session, user)
    conn = GoogleConnection(
        workspace_id=workspace_id,
        google_account_email="acct@example.com",
        google_sub="g-sub-1",
        granted_scopes=["openid", "email"],
        refresh_token_encrypted=b"\x00\x01",
        encryption_key_version=1,
    )
    db_session.add(conn)
    await db_session.flush()
    assert conn.status == ConnectionStatus.ACTIVE


async def test_connection_unique_user_google_sub(
    db_session: AsyncSession, make_user
) -> None:
    user = await make_user(sub="sub-1")
    workspace_id = await owner_workspace_id(db_session, user)
    common = {
        "workspace_id": workspace_id,
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


async def test_workspace_cascade_deletes_connections(
    db_session: AsyncSession, make_user
) -> None:
    """Les google_connections dependent desormais du workspace, pas directement
    de l'utilisateur (cf. commentaire dans app/models/user.py) : Workspace.owner_user_id
    est ondelete=RESTRICT, donc supprimer directement le user proprietaire echouerait.
    Le cascade passe maintenant par la suppression du workspace lui-meme."""
    user = await make_user(sub="sub-1")
    workspace_id = await owner_workspace_id(db_session, user)
    db_session.add(
        GoogleConnection(
            workspace_id=workspace_id,
            google_account_email="a@example.com",
            google_sub="c-sub",
            granted_scopes=["openid"],
            refresh_token_encrypted=b"x",
            encryption_key_version=1,
        )
    )
    await db_session.flush()
    workspace = await db_session.get(Workspace, workspace_id)
    await db_session.delete(workspace)
    await db_session.flush()
    remaining = (await db_session.execute(select(GoogleConnection))).scalars().all()
    assert remaining == []
