"""Endpoints workspaces : liste, invitation, acceptation, retrait de membre."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, EmailStr
from sqlalchemy import select

from app.api.deps import CurrentUserDep, EmailSenderDep, SessionDep, SettingsDep
from app.models.workspace import Workspace
from app.models.workspace_member import WorkspaceMember
from app.services.workspace_invites import (
    InvitationEmailMismatch,
    InvitationInvalid,
    accept_invitation,
    create_invitation,
    get_invitation,
)
from app.services.workspaces import require_owner

router = APIRouter(tags=["workspaces"])


class WorkspaceOut(BaseModel):
    id: UUID
    name: str
    role: str


class InviteRequest(BaseModel):
    invited_email: EmailStr


class InvitationOut(BaseModel):
    id: UUID
    workspace_id: UUID
    invited_email: str
    token: str
    status: str


@router.get("/workspaces/mine", response_model=list[WorkspaceOut])
async def list_my_workspaces(user: CurrentUserDep, session: SessionDep) -> list[WorkspaceOut]:
    rows = (
        await session.execute(
            select(Workspace, WorkspaceMember.role)
            .join(WorkspaceMember, WorkspaceMember.workspace_id == Workspace.id)
            .where(WorkspaceMember.user_id == user.id)
        )
    ).all()
    return [WorkspaceOut(id=ws.id, name=ws.name, role=role) for ws, role in rows]


@router.post(
    "/workspaces/{workspace_id}/invitations", response_model=InvitationOut, status_code=status.HTTP_201_CREATED
)
async def invite_to_workspace(
    workspace_id: UUID, body: InviteRequest, user: CurrentUserDep, session: SessionDep,
    email_sender: EmailSenderDep, settings: SettingsDep,
) -> InvitationOut:
    await require_owner(session, workspace_id=workspace_id, user_id=user.id)
    invitation = await create_invitation(
        session, workspace_id=workspace_id, invited_email=body.invited_email, invited_by_user_id=user.id
    )
    await session.commit()
    link = f"{settings.frontend_base_url}/invitations/{invitation.token}"
    await email_sender.send(
        to=body.invited_email, subject="Invitation à rejoindre un espace",
        body_text=f"Tu as ete invite a rejoindre un espace de travail : {link}",
    )
    return InvitationOut(
        id=invitation.id, workspace_id=invitation.workspace_id,
        invited_email=invitation.invited_email, token=invitation.token, status=invitation.status,
    )


@router.get("/invitations/{token}", response_model=InvitationOut)
async def get_invitation_endpoint(token: str, session: SessionDep) -> InvitationOut:
    invitation = await get_invitation(session, token)
    if invitation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="invitation introuvable")
    return InvitationOut(
        id=invitation.id, workspace_id=invitation.workspace_id,
        invited_email=invitation.invited_email, token=invitation.token, status=invitation.status,
    )


@router.post("/invitations/{token}/accept")
async def accept_invitation_endpoint(token: str, user: CurrentUserDep, session: SessionDep) -> dict[str, str]:
    try:
        await accept_invitation(session, token=token, user=user)
    except InvitationEmailMismatch as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from None
    except InvitationInvalid as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from None
    await session.commit()
    return {"status": "ok"}


@router.delete("/workspaces/{workspace_id}/members/{member_user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_member(
    workspace_id: UUID, member_user_id: UUID, user: CurrentUserDep, session: SessionDep
) -> None:
    await require_owner(session, workspace_id=workspace_id, user_id=user.id)
    if member_user_id == user.id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="le proprietaire ne peut pas se retirer")
    row = (
        await session.execute(
            select(WorkspaceMember).where(
                WorkspaceMember.workspace_id == workspace_id, WorkspaceMember.user_id == member_user_id
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="membre introuvable")
    await session.delete(row)
    await session.commit()
