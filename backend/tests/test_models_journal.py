from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_log import AuditLog
from app.models.audit_snapshot import AuditSnapshot
from app.models.enums import (
    AuditResult,
    IssueCategory,
    IssueSeverity,
    IssueStatus,
    SnapshotSource,
)
from app.models.issue_item import IssueItem
from app.models.user import User
from app.models.website import Website


async def _site(session: AsyncSession) -> Website:
    user = User(email="j@example.com", google_sub="sub-j")
    session.add(user)
    await session.flush()
    site = Website(user_id=user.id, domain="j.com", display_name="J")
    session.add(site)
    await session.flush()
    return site


async def test_snapshot_stores_jsonb_metrics(db_session: AsyncSession) -> None:
    site = await _site(db_session)
    snap = AuditSnapshot(
        website_id=site.id,
        captured_at=datetime.now(UTC),
        source=SnapshotSource.PAGESPEED,
        metrics={"performance": 0.82, "lcp_ms": 2400},
    )
    db_session.add(snap)
    await db_session.flush()
    await db_session.refresh(snap)
    assert snap.metrics["lcp_ms"] == 2400


async def test_issue_status_defaults_todo(db_session: AsyncSession) -> None:
    site = await _site(db_session)
    issue = IssueItem(
        website_id=site.id,
        title="Balise title manquante",
        description="…",
        category=IssueCategory.SEO,
        severity=IssueSeverity.MEDIUM,
        fingerprint="seo:missing-title:/",
        detected_at=datetime.now(UTC),
    )
    db_session.add(issue)
    await db_session.flush()
    assert issue.status == IssueStatus.TODO


async def test_issue_unique_fingerprint_per_site(db_session: AsyncSession) -> None:
    site = await _site(db_session)
    common = {
        "website_id": site.id,
        "title": "x",
        "description": "x",
        "category": IssueCategory.SEO,
        "severity": IssueSeverity.LOW,
        "fingerprint": "dup",
        "detected_at": datetime.now(UTC),
    }
    db_session.add(IssueItem(**common))
    await db_session.flush()
    db_session.add(IssueItem(**common))
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_snapshot_delete_nulls_issue_link(db_session: AsyncSession) -> None:
    site = await _site(db_session)
    snap = AuditSnapshot(
        website_id=site.id,
        captured_at=datetime.now(UTC),
        source=SnapshotSource.GA4,
        metrics={},
    )
    db_session.add(snap)
    await db_session.flush()
    issue = IssueItem(
        website_id=site.id,
        title="x",
        description="x",
        category=IssueCategory.ANALYTICS,
        severity=IssueSeverity.LOW,
        fingerprint="fp",
        detected_at=datetime.now(UTC),
        source_snapshot_id=snap.id,
    )
    db_session.add(issue)
    await db_session.flush()
    await db_session.delete(snap)
    await db_session.flush()
    await db_session.refresh(issue)
    assert issue.source_snapshot_id is None


async def test_audit_log_survives_user_delete(db_session: AsyncSession) -> None:
    user = User(email="a@example.com", google_sub="sub-a")
    db_session.add(user)
    await db_session.flush()
    log = AuditLog(
        user_id=user.id,
        action="google_connection.created",
        result=AuditResult.SUCCESS,
    )
    db_session.add(log)
    await db_session.flush()
    await db_session.delete(user)
    await db_session.flush()
    db_session.expire_all()
    rows = (await db_session.execute(select(AuditLog))).scalars().all()
    assert len(rows) == 1
    assert rows[0].user_id is None
