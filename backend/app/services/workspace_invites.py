"""Invitations a rejoindre un workspace : creation, consultation, acceptation."""

from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.models.workspace_invitation import WorkspaceInvitation
from app.models.workspace_member import WorkspaceMember
from app.services.workspaces import is_member

_INVITATION_TTL = timedelta(days=7)


class InvitationInvalid(Exception):
    """Token inconnu, expire ou deja utilise/revoque."""


class InvitationEmailMismatch(Exception):
    """L'utilisateur qui accepte n'a pas l'email invite."""


async def create_invitation(
    session: AsyncSession, *, workspace_id: UUID, invited_email: str, invited_by_user_id: UUID
) -> WorkspaceInvitation:
    invitation = WorkspaceInvitation(
        workspace_id=workspace_id,
        invited_email=invited_email,
        token=secrets.token_urlsafe(32),
        invited_by_user_id=invited_by_user_id,
        status="pending",
        expires_at=datetime.now(UTC) + _INVITATION_TTL,
    )
    session.add(invitation)
    await session.flush()
    return invitation


async def get_invitation(session: AsyncSession, token: str) -> WorkspaceInvitation | None:
    return (
        await session.execute(
            select(WorkspaceInvitation).where(WorkspaceInvitation.token == token)
        )
    ).scalar_one_or_none()


async def accept_invitation(
    session: AsyncSession, *, token: str, user: User
) -> WorkspaceMember:
    invitation = await get_invitation(session, token)
    if invitation is None or invitation.status != "pending":
        raise InvitationInvalid("invitation introuvable ou deja utilisee")
    if invitation.expires_at < datetime.now(UTC):
        raise InvitationInvalid("invitation expiree")
    if invitation.invited_email.lower() != user.email.lower():
        raise InvitationEmailMismatch("cette invitation est nominative")

    if await is_member(session, workspace_id=invitation.workspace_id, user_id=user.id):
        invitation.status = "accepted"
        invitation.accepted_at = datetime.now(UTC)
        await session.flush()
        return (
            await session.execute(
                select(WorkspaceMember).where(
                    WorkspaceMember.workspace_id == invitation.workspace_id,
                    WorkspaceMember.user_id == user.id,
                )
            )
        ).scalar_one()

    member = WorkspaceMember(workspace_id=invitation.workspace_id, user_id=user.id, role="member")
    session.add(member)
    invitation.status = "accepted"
    invitation.accepted_at = datetime.now(UTC)
    await session.flush()
    return member
