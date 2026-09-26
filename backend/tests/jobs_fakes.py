"""Doubles et utilitaires des tests du lot B (tâches planifiées) : aucun réseau."""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.website import Website
from app.services.jobs.runner import JobLimits
from tests.conftest import owner_workspace_id

LIMITS = JobLimits(lease=timedelta(minutes=15), max_attempts=3, workspace_concurrency=2)


async def make_site(db_session: AsyncSession, make_user, domain: str) -> Website:
    user = await make_user(sub=f"jobs-{domain}")
    workspace_id = await owner_workspace_id(db_session, user)
    site = Website(workspace_id=workspace_id, domain=domain, display_name=domain)
    db_session.add(site)
    await db_session.flush()
    return site
