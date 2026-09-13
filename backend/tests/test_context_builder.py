import json
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_snapshot import AuditSnapshot
from app.models.enums import (
    IssueCategory,
    IssueSeverity,
    IssueStatus,
    SnapshotSource,
)
from app.models.issue_item import IssueItem
from app.models.website import Website
from app.services.advisor.context_builder import build_context
from tests.conftest import UserFactory, owner_workspace_id


async def _site(db_session: AsyncSession, workspace_id) -> Website:
    site = Website(
        workspace_id=workspace_id, domain="ctx.test", display_name="Ctx", detected_stack=None
    )
    db_session.add(site)
    await db_session.flush()
    return site


async def test_context_is_deterministic_sorted_json(
    db_session: AsyncSession, make_user: UserFactory
) -> None:
    user = await make_user(sub="ctx-1")
    site = await _site(db_session, await owner_workspace_id(db_session, user))
    db_session.add(
        AuditSnapshot(
            website_id=site.id,
            captured_at=datetime(2026, 9, 1, tzinfo=UTC),
            source=SnapshotSource.COMPOSITE,
            metrics={
                "ga4": {"score": 40, "degraded": True},
                "gsc": {"score": 88},
                "cwv": {"score": 70, "lcp_ms": 3000, "inp_ms": 150, "cls": 0.05},
                "gtm": {
                    "containers": ["GTM-X"],
                    "snippet_form": "standard",
                    "consent_platform": None,
                    "findings": [],
                },
            },
        )
    )
    db_session.add(
        IssueItem(
            website_id=site.id,
            title="purchase params",
            description="...",
            category=IssueCategory.ANALYTICS,
            severity=IssueSeverity.CRITICAL,
            status=IssueStatus.TODO,
            fingerprint="f" * 64,
            detected_at=datetime(2026, 9, 1, tzinfo=UTC),
        )
    )
    await db_session.flush()

    raw = await build_context(db_session, site)
    assert raw == json.dumps(json.loads(raw), sort_keys=True, ensure_ascii=False, indent=2)
    data = json.loads(raw)
    assert data["site"]["domain"] == "ctx.test"
    assert data["latest_snapshot"]["scores"] == {"ga4": 40, "gsc": 88, "cwv": 70}
    assert data["latest_snapshot"]["gtm"]["containers"] == ["GTM-X"]
    assert data["open_issues"][0]["title"] == "purchase params"
    assert "ga4_disconnected" in data["data_gaps"]


async def test_context_without_snapshot_flags_gap(
    db_session: AsyncSession, make_user: UserFactory
) -> None:
    user = await make_user(sub="ctx-2")
    site = await _site(db_session, await owner_workspace_id(db_session, user))
    data = json.loads(await build_context(db_session, site))
    assert data["latest_snapshot"] is None
    assert "no_snapshot" in data["data_gaps"]
    assert data["open_issues"] == []
