from sqlalchemy.ext.asyncio import AsyncSession

from app.services.oauth_state import consume_oauth_state, create_oauth_transaction
from tests.conftest import UserFactory, owner_workspace_id


async def test_transaction_roundtrips_workspace_id(
    db_session: AsyncSession, make_user: UserFactory
) -> None:
    user = await make_user(sub="test-user", email="test@example.com")
    workspace_id = await owner_workspace_id(db_session, user)
    transaction = await create_oauth_transaction(
        db_session, user_id=None, workspace_id=workspace_id,
        redirect_to="/connections", ttl_seconds=600,
    )
    await db_session.commit()
    consumed = await consume_oauth_state(db_session, transaction.state)
    assert consumed is not None
    assert consumed.workspace_id == workspace_id


async def test_transaction_workspace_id_defaults_to_none_for_login(db_session: AsyncSession) -> None:
    transaction = await create_oauth_transaction(
        db_session, user_id=None, workspace_id=None,
        redirect_to=None, ttl_seconds=600,
    )
    await db_session.commit()
    consumed = await consume_oauth_state(db_session, transaction.state)
    assert consumed is not None
    assert consumed.workspace_id is None
