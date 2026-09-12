"""Appartenance a un workspace : verifications reutilisees par tous les endpoints
qui exposaient auparavant `_owned_website` (une copie par fichier)."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.website import Website
from app.models.workspace import Workspace
from app.models.workspace_member import WorkspaceMember

if TYPE_CHECKING:
    from app.models.user import User


async def user_workspace_ids(session: AsyncSession, user_id: UUID) -> list[UUID]:
    rows = (
        await session.execute(
            select(WorkspaceMember.workspace_id).where(WorkspaceMember.user_id == user_id)
        )
    ).scalars().all()
    return list(rows)


async def is_member(session: AsyncSession, *, workspace_id: UUID, user_id: UUID) -> bool:
    row = (
        await session.execute(
            select(WorkspaceMember.id).where(
                WorkspaceMember.workspace_id == workspace_id,
                WorkspaceMember.user_id == user_id,
            )
        )
    ).scalar_one_or_none()
    return row is not None


async def owned_website(session: AsyncSession, *, website_id: UUID, user_id: UUID) -> Website:
    site = await session.get(Website, website_id)
    if site is None or not await is_member(session, workspace_id=site.workspace_id, user_id=user_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="site introuvable")
    return site


async def create_workspace_for_user(
    session: AsyncSession, *, user: User, name: str | None = None
) -> Workspace:
    workspace = Workspace(name=name or user.display_name or user.email, owner_user_id=user.id)
    session.add(workspace)
    await session.flush()
    session.add(WorkspaceMember(workspace_id=workspace.id, user_id=user.id, role="owner"))
    await session.flush()
    return workspace
