"""Aides de developpement local — actives uniquement quand
``GOOGLE_OAUTH_MOCK=true``. Ne jamais exposer en staging/prod.
"""

from __future__ import annotations

from datetime import timedelta
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel
from sqlalchemy import select

from app.api.deps import SessionDep, SettingsDep
from app.models.audit_snapshot import AuditSnapshot
from app.models.enums import StackKind
from app.models.user import User
from app.models.website import Website
from app.models.workspace import Workspace
from app.models.workspace_member import WorkspaceMember
from app.security.session import issue_session
from app.services.audit_engine import run_audit
from app.services.audit_probe import MockAuditProbe
from app.services.stack_detector import demo_detector

router = APIRouter(prefix="/dev", tags=["dev"])

_DEV_EMAIL = "dev@controlcenter.local"
_DEV_SUB = "dev-local-user"
_SESSION_MAX_AGE = int(timedelta(days=30).total_seconds())

# Sites de demo, alignes sur frontend/lib/mock/workspaces.ts.
_SEED: list[tuple[str, str]] = [
    ("boutique-verte.fr", "Boutique Verte"),
    ("atelier-nord.com", "Atelier Nord"),
    ("studiolumen.io", "Studio Lumen"),
    ("cap-horizon.co", "Cap Horizon"),
]


async def _require_dev_mode(settings: SettingsDep) -> None:
    if not settings.google_oauth_mock:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="indisponible")


class DevWorkspace(BaseModel):
    id: UUID
    domain: str
    display_name: str
    detected_stack: StackKind | None


@router.get(
    "/workspaces",
    response_model=list[DevWorkspace],
    dependencies=[Depends(_require_dev_mode)],
)
async def dev_workspaces(
    response: Response,
    session: SessionDep,
    settings: SettingsDep,
) -> list[Website]:
    """Cree (idempotent) l'utilisateur de dev + 4 sites seedes et scannes,
    pose le cookie de session, renvoie la liste."""
    user = (
        await session.execute(select(User).where(User.google_sub == _DEV_SUB))
    ).scalar_one_or_none()
    if user is None:
        user = User(email=_DEV_EMAIL, google_sub=_DEV_SUB, display_name="Dev local")
        session.add(user)
        await session.flush()

    workspace = (
        await session.execute(
            select(Workspace).join(WorkspaceMember).where(WorkspaceMember.user_id == user.id)
        )
    ).scalars().first()
    if workspace is None:
        workspace = Workspace(name="Dev local", owner_user_id=user.id)
        session.add(workspace)
        await session.flush()
        session.add(WorkspaceMember(workspace_id=workspace.id, user_id=user.id, role="owner"))
        await session.flush()

    sites: list[Website] = []
    for domain, name in _SEED:
        site = (
            await session.execute(
                select(Website).where(
                    Website.workspace_id == workspace.id, Website.domain == domain
                )
            )
        ).scalar_one_or_none()
        if site is None:
            site = Website(workspace_id=workspace.id, domain=domain, display_name=name)
            session.add(site)
            await session.flush()

        latest = (
            await session.execute(
                select(AuditSnapshot)
                .where(AuditSnapshot.website_id == site.id)
                .order_by(AuditSnapshot.captured_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        # Re-scanne si jamais scanne ou si le snapshot precede la derniere
        # montee de version de la sonde (diagnostics CWV structures, echantillon
        # d'URLs GSC...) — self-healing en dev.
        metrics = latest.metrics if latest is not None else {}
        cwv, gsc = metrics.get("cwv", {}), metrics.get("gsc", {})
        stale = "costly_entities" not in cwv or "sample_urls" not in gsc
        if latest is None or stale:
            await run_audit(
                session,
                website=site,
                probe=MockAuditProbe(),
                user_id=user.id,
                detector=demo_detector,
            )
        sites.append(site)

    await session.commit()

    response.set_cookie(
        settings.session_cookie_name,
        issue_session(user.id, secret=settings.app_secret_key.get_secret_value()),
        max_age=_SESSION_MAX_AGE,
        httponly=True,
        samesite="lax",
        secure=settings.environment != "local",
    )
    return sites
