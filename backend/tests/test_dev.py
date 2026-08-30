"""Endpoint d'amorçage dev : /api/v1/dev/workspaces."""

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_snapshot import AuditSnapshot
from app.models.issue_item import IssueItem
from app.models.user import User
from app.models.website import Website


async def test_dev_workspaces_seeds_scans_and_authenticates(
    db_client: AsyncClient, db_session: AsyncSession
) -> None:
    resp = await db_client.get("/api/v1/dev/workspaces")
    assert resp.status_code == 200
    body = resp.json()
    domains = {w["domain"] for w in body}
    assert domains == {
        "boutique-verte.fr",
        "atelier-nord.com",
        "studiolumen.io",
        "cap-horizon.co",
    }
    boutique = next(w for w in body if w["domain"] == "boutique-verte.fr")
    assert boutique["detected_stack"] == "nextjs"
    assert "cc_session" in resp.cookies

    # les sites seedes ont ete scannes (snapshot + issues)
    site_id = boutique["id"]
    snap = (
        (await db_session.execute(select(AuditSnapshot).where(AuditSnapshot.website_id == site_id)))
        .scalars()
        .all()
    )
    assert len(snap) == 1
    issues = (
        (await db_session.execute(select(IssueItem).where(IssueItem.website_id == site_id)))
        .scalars()
        .all()
    )
    assert len(issues) >= 3

    # le cookie pose permet d'appeler un endpoint protege
    overview = await db_client.get(f"/api/v1/websites/{site_id}/overview")
    assert overview.status_code == 200


async def test_dev_workspaces_is_idempotent(
    db_client: AsyncClient, db_session: AsyncSession
) -> None:
    first = (await db_client.get("/api/v1/dev/workspaces")).json()
    second = (await db_client.get("/api/v1/dev/workspaces")).json()
    assert {w["id"] for w in first} == {w["id"] for w in second}

    users = (await db_session.execute(select(User))).scalars().all()
    assert len([u for u in users if u.google_sub == "dev-local-user"]) == 1
    sites = (await db_session.execute(select(Website))).scalars().all()
    assert len(sites) == 4
