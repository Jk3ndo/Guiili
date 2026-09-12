from datetime import UTC, datetime, timedelta

import pytest

from app.models.workspace_invitation import WorkspaceInvitation
from app.services.workspace_invites import (
    InvitationEmailMismatch,
    InvitationInvalid,
    accept_invitation,
    create_invitation,
    get_invitation,
)
from app.services.workspaces import create_workspace_for_user
from tests.conftest import owner_workspace_id


async def test_create_workspace_for_user_makes_owner_membership(db_session, make_user) -> None:
    user = await make_user(sub="ws-1")
    workspace = await create_workspace_for_user(db_session, user=user, name="Mon espace")
    assert workspace.owner_user_id == user.id
    assert workspace.name == "Mon espace"


async def test_create_invitation_has_token_and_expiry(db_session, make_user) -> None:
    owner = await make_user(sub="inv-owner")
    ws_id = await owner_workspace_id(db_session, owner)
    invitation = await create_invitation(
        db_session, workspace_id=ws_id, invited_email="friend@example.com",
        invited_by_user_id=owner.id,
    )
    assert invitation.status == "pending"
    assert invitation.token
    assert invitation.expires_at > datetime.now(UTC)


async def test_accept_invitation_creates_membership(db_session, make_user) -> None:
    owner = await make_user(sub="inv-owner-2")
    ws_id = await owner_workspace_id(db_session, owner)
    invitation = await create_invitation(
        db_session, workspace_id=ws_id, invited_email="friend2@example.com",
        invited_by_user_id=owner.id,
    )
    friend = await make_user(sub="friend-2", email="friend2@example.com")

    member = await accept_invitation(db_session, token=invitation.token, user=friend)

    assert member.workspace_id == ws_id
    assert member.role == "member"
    refreshed = await db_session.get(WorkspaceInvitation, invitation.id)
    assert refreshed.status == "accepted"
    assert refreshed.accepted_at is not None


async def test_accept_invitation_rejects_email_mismatch(db_session, make_user) -> None:
    owner = await make_user(sub="inv-owner-3")
    ws_id = await owner_workspace_id(db_session, owner)
    invitation = await create_invitation(
        db_session, workspace_id=ws_id, invited_email="expected@example.com",
        invited_by_user_id=owner.id,
    )
    someone_else = await make_user(sub="someone-else", email="someone@example.com")

    with pytest.raises(InvitationEmailMismatch):
        await accept_invitation(db_session, token=invitation.token, user=someone_else)


async def test_accept_invitation_rejects_expired(db_session, make_user) -> None:
    owner = await make_user(sub="inv-owner-4")
    ws_id = await owner_workspace_id(db_session, owner)
    invitation = await create_invitation(
        db_session, workspace_id=ws_id, invited_email="friend4@example.com",
        invited_by_user_id=owner.id,
    )
    invitation.expires_at = datetime.now(UTC) - timedelta(days=1)
    await db_session.flush()
    friend = await make_user(sub="friend-4", email="friend4@example.com")

    with pytest.raises(InvitationInvalid):
        await accept_invitation(db_session, token=invitation.token, user=friend)


async def test_accept_invitation_rejects_already_used_token(db_session, make_user) -> None:
    owner = await make_user(sub="inv-owner-5")
    ws_id = await owner_workspace_id(db_session, owner)
    invitation = await create_invitation(
        db_session, workspace_id=ws_id, invited_email="friend5@example.com",
        invited_by_user_id=owner.id,
    )
    friend = await make_user(sub="friend-5", email="friend5@example.com")
    await accept_invitation(db_session, token=invitation.token, user=friend)

    with pytest.raises(InvitationInvalid):
        await accept_invitation(db_session, token=invitation.token, user=friend)


async def test_get_invitation_unknown_token_returns_none(db_session) -> None:
    assert await get_invitation(db_session, "not-a-real-token") is None
