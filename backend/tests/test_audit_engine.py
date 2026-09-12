"""Moteur d'audit : regles de detection + dedup via fingerprint + auto-resolution."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_log import AuditLog
from app.models.audit_snapshot import AuditSnapshot
from app.models.enums import IssueCategory, IssueSeverity, IssueStatus, StackKind
from app.models.issue_item import IssueItem
from app.models.website import Website
from app.services.audit_engine import detect_anomalies, run_audit
from app.services.audit_probe import (
    AuditProbe,
    CwvSignals,
    Ga4Signals,
    GscSignals,
    MockAuditProbe,
    ProbeData,
)
from app.services.gtm_check import GtmCheck, GtmFinding
from app.services.stack_detector import StackDetection
from app.services.tls_check import TlsStatus
from tests.conftest import UserFactory, owner_workspace_id


async def _detector(url: str) -> StackDetection:
    _ = url
    return StackDetection(StackKind.NEXTJS, ("test",), 0.9)


class _StubProbe(AuditProbe):
    def __init__(self, data: ProbeData) -> None:
        self._data = data

    async def collect(
        self, *, website: Website, stack: StackKind, session: AsyncSession | None = None
    ) -> ProbeData:
        _ = (website, stack, session)
        return self._data


_CLEAN = ProbeData(
    ga4=Ga4Signals(score=95),
    gsc=GscSignals(score=96, valid_pages=200, excluded_pages=4),
    cwv=CwvSignals(score=95, lcp_ms=1800, inp_ms=120, cls=0.02),
)


async def _website(session: AsyncSession, workspace_id, *, domain: str) -> Website:
    site = Website(workspace_id=workspace_id, domain=domain, display_name=domain)
    session.add(site)
    await session.flush()
    return site


# --------------------------------------------------------------------------- #
#  Regles pures                                                                #
# --------------------------------------------------------------------------- #


def test_rules_for_boutique_verte() -> None:
    data = ProbeData(
        ga4=Ga4Signals(score=92, purchase_missing_params=("value", "currency")),
        gsc=GscSignals(
            score=78,
            valid_pages=214,
            excluded_pages=37,
            noindex_pages=12,
            noindex_on_products=True,
        ),
        cwv=CwvSignals(score=61, lcp_ms=3400, inp_ms=184, cls=0.08),
    )
    rules = {a.rule_id: a for a in detect_anomalies(data)}
    assert rules["ga4_purchase_params"].severity is IssueSeverity.CRITICAL
    assert rules["gsc_noindex"].severity is IssueSeverity.HIGH
    assert rules["cwv_lcp"].severity is IssueSeverity.HIGH
    assert "cwv_inp" not in rules  # 184 ms est dans la cible
    assert "gsc_coverage" not in rules  # le motif noindex prend le pas


def test_rules_for_studio_lumen() -> None:
    data = ProbeData(
        ga4=Ga4Signals(score=88),
        gsc=GscSignals(score=95, valid_pages=142, excluded_pages=7),
        cwv=CwvSignals(score=79, lcp_ms=1900, inp_ms=260, cls=0.04),
    )
    rules = {a.rule_id for a in detect_anomalies(data)}
    assert rules == {"cwv_inp"}


def test_clean_site_has_no_anomaly() -> None:
    assert detect_anomalies(_CLEAN) == []


def _tls(status: str, days: int | None = None) -> TlsStatus:
    expires = datetime.now(UTC) + timedelta(days=days) if days is not None else None
    return TlsStatus(
        host="x.fr",
        status=status,
        checked_at=datetime.now(UTC),
        expires_at=expires,
        days_remaining=days,
    )


@pytest.mark.parametrize(
    ("status", "days", "expected_severity"),
    [
        ("expired", -3, IssueSeverity.CRITICAL),
        ("expiring_soon", 5, IssueSeverity.CRITICAL),
        ("expiring_soon", 12, IssueSeverity.HIGH),
        ("expiring_soon", 25, IssueSeverity.MEDIUM),
        ("hostname_mismatch", 100, IssueSeverity.HIGH),
        ("self_signed", 100, IssueSeverity.HIGH),
    ],
)
def test_ssl_rule_severity(status: str, days: int, expected_severity: IssueSeverity) -> None:
    out = detect_anomalies(_CLEAN, tls=_tls(status, days))
    ssl = next(a for a in out if a.rule_id == "ssl_certificate")
    assert ssl.severity is expected_severity
    assert ssl.subject == "certificate"


def test_ssl_rule_silent_when_valid_or_unreachable() -> None:
    assert detect_anomalies(_CLEAN, tls=_tls("valid", 90)) == []
    assert detect_anomalies(_CLEAN, tls=_tls("unreachable")) == []


def test_lcp_rule_lists_heavy_assets_from_pagespeed() -> None:
    data = ProbeData(
        ga4=Ga4Signals(score=0),
        gsc=GscSignals(score=0),
        cwv=CwvSignals(
            score=40,
            lcp_ms=4200,
            cls=0.02,
            heavy_assets=("hero-banner.jpg", "collection.png"),
            lcp_element="<img class='hero'>",
            field_data=True,
        ),
    )
    lcp = next(a for a in detect_anomalies(data) if a.rule_id == "cwv_lcp")
    assert lcp.severity is IssueSeverity.CRITICAL  # > 4000 ms
    assert "hero-banner.jpg" in lcp.description
    assert "collection.png" in lcp.description
    assert "terrain" in lcp.description
    assert "<img class='hero'>" in lcp.description


def test_inp_rule_lists_third_party_scripts() -> None:
    data = ProbeData(
        ga4=Ga4Signals(score=0),
        gsc=GscSignals(score=0),
        cwv=CwvSignals(
            score=55,
            inp_ms=340,
            cls=0.0,
            third_party_scripts=("Google Tag Manager", "Hotjar"),
            js_execution_ms=2100,
            field_data=False,
        ),
    )
    inp = next(a for a in detect_anomalies(data) if a.rule_id == "cwv_inp")
    assert "Google Tag Manager" in inp.description
    assert "Hotjar" in inp.description
    assert "2100 ms" in inp.description
    assert "labo" in inp.description


def _gtm(*findings: GtmFinding) -> GtmCheck:
    return GtmCheck(containers=("GTM-XXXX",), snippet_form="standard", findings=findings)


def test_gtm_high_and_medium_findings_become_tracking_anomalies() -> None:
    gtm = _gtm(
        GtmFinding("gtm_preview_csp_block", "high", "CSP bloque la previsualisation GTM", "..."),
        GtmFinding("gtm_consent_gated", "medium", "GTM gele par le consentement", "..."),
        GtmFinding("gtm_snippet_not_in_head", "low", "Snippet hors <head>", "..."),
    )
    out = {a.rule_id: a for a in detect_anomalies(_CLEAN, gtm=gtm)}
    assert out["gtm_preview_csp_block"].category is IssueCategory.TRACKING
    assert out["gtm_preview_csp_block"].severity is IssueSeverity.HIGH
    assert out["gtm_consent_gated"].severity is IssueSeverity.MEDIUM
    assert "gtm_snippet_not_in_head" not in out  # low => pas d'issue


def test_gtm_none_or_clean_adds_nothing() -> None:
    assert detect_anomalies(_CLEAN, gtm=None) == []
    assert detect_anomalies(_CLEAN, gtm=_gtm()) == []


# --------------------------------------------------------------------------- #
#  run_audit                                                                   #
# --------------------------------------------------------------------------- #


async def test_run_audit_writes_snapshot_and_issues(
    db_session: AsyncSession, make_user: UserFactory
) -> None:
    user = await make_user(sub="au-1")
    site = await _website(db_session, await owner_workspace_id(db_session, user), domain="boutique-verte.fr")

    result = await run_audit(
        db_session,
        website=site,
        probe=MockAuditProbe(),
        user_id=user.id,
        detector=_detector,
    )

    assert site.detected_stack is StackKind.NEXTJS
    snap = await db_session.get(AuditSnapshot, result.snapshot.id)
    assert snap is not None
    assert snap.metrics["ga4"]["score"] == 92

    issues = (
        (await db_session.execute(select(IssueItem).where(IssueItem.website_id == site.id)))
        .scalars()
        .all()
    )
    assert {i.category.value for i in issues} >= {"analytics", "seo", "cwv"}
    assert all(len(i.fingerprint) == 64 for i in issues)

    log = (
        await db_session.execute(select(AuditLog).where(AuditLog.resource_id == str(site.id)))
    ).scalar_one()
    assert log.action == "website.scan"
    assert len(log.request_payload_hash) == 64


async def test_run_audit_persists_gtm_block_and_tracking_issue(
    db_session: AsyncSession, make_user: UserFactory
) -> None:
    user = await make_user(sub="au-gtm")
    site = await _website(db_session, await owner_workspace_id(db_session, user), domain="gtm-site.test")

    async def gtm_checker(domain: str) -> GtmCheck:
        _ = domain
        return GtmCheck(
            containers=("GTM-AAA1111",),
            snippet_form="standard",
            findings=(
                GtmFinding("gtm_consent_gated", "medium", "GTM gele par le consentement", "detail"),
            ),
        )

    result = await run_audit(
        db_session,
        website=site,
        probe=MockAuditProbe(),
        detector=_detector,
        gtm_checker=gtm_checker,
    )

    assert result.metrics["gtm"]["snippet_form"] == "standard"
    assert result.metrics["gtm"]["containers"] == ["GTM-AAA1111"]
    assert any(i.category is IssueCategory.TRACKING for i in result.created)


async def test_run_audit_without_gtm_checker_has_null_block(
    db_session: AsyncSession, make_user: UserFactory
) -> None:
    user = await make_user(sub="au-nogtm")
    site = await _website(db_session, await owner_workspace_id(db_session, user), domain="plain.test")
    result = await run_audit(
        db_session, website=site, probe=MockAuditProbe(), detector=_detector
    )
    assert result.metrics["gtm"] is None


async def test_rescan_does_not_duplicate_issues(
    db_session: AsyncSession, make_user: UserFactory
) -> None:
    user = await make_user(sub="au-2")
    site = await _website(db_session, await owner_workspace_id(db_session, user), domain="boutique-verte.fr")

    first = await run_audit(db_session, website=site, probe=MockAuditProbe(), detector=_detector)
    count_1 = (
        await db_session.execute(
            select(func.count()).select_from(IssueItem).where(IssueItem.website_id == site.id)
        )
    ).scalar_one()
    assert len(first.created) == count_1
    assert first.updated == []

    second = await run_audit(db_session, website=site, probe=MockAuditProbe(), detector=_detector)
    count_2 = (
        await db_session.execute(
            select(func.count()).select_from(IssueItem).where(IssueItem.website_id == site.id)
        )
    ).scalar_one()
    assert count_2 == count_1  # aucun doublon
    assert second.created == []
    assert len(second.updated) == count_1


async def test_fingerprint_stable_when_details_change(
    db_session: AsyncSession, make_user: UserFactory
) -> None:
    user = await make_user(sub="au-3")
    site = await _website(db_session, await owner_workspace_id(db_session, user), domain="x.test")

    probe_a = _StubProbe(
        ProbeData(
            ga4=Ga4Signals(score=80, purchase_missing_params=("value", "currency")),
            gsc=GscSignals(score=90, valid_pages=100, excluded_pages=2),
            cwv=CwvSignals(score=90),
        )
    )
    await run_audit(db_session, website=site, probe=probe_a, detector=_detector)

    probe_b = _StubProbe(
        ProbeData(
            ga4=Ga4Signals(score=80, purchase_missing_params=("value",)),
            gsc=GscSignals(score=90, valid_pages=100, excluded_pages=2),
            cwv=CwvSignals(score=90),
        )
    )
    result = await run_audit(db_session, website=site, probe=probe_b, detector=_detector)

    purchase = (
        (
            await db_session.execute(
                select(IssueItem).where(
                    IssueItem.website_id == site.id,
                    IssueItem.category == "analytics",
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(purchase) == 1  # meme fingerprint -> pas de doublon
    assert "value" in purchase[0].description
    assert "currency" not in purchase[0].description
    assert purchase[0] in result.updated


async def test_disappearing_anomaly_is_auto_resolved_then_reopened(
    db_session: AsyncSession, make_user: UserFactory
) -> None:
    user = await make_user(sub="au-4")
    site = await _website(db_session, await owner_workspace_id(db_session, user), domain="boutique-verte.fr")

    await run_audit(db_session, website=site, probe=MockAuditProbe(), detector=_detector)
    purchase = (
        await db_session.execute(
            select(IssueItem).where(
                IssueItem.website_id == site.id,
                IssueItem.category == "analytics",
                IssueItem.status != "dismissed",
            )
        )
    ).scalar_one()
    assert purchase.status is IssueStatus.TODO

    # scan « propre » -> l'anomalie a disparu
    clean = await run_audit(db_session, website=site, probe=_StubProbe(_CLEAN), detector=_detector)
    await db_session.refresh(purchase)
    assert purchase.status is IssueStatus.FIXED
    assert purchase.resolved_at is not None
    assert purchase in clean.resolved

    # l'anomalie revient -> l'issue repasse a todo
    await run_audit(db_session, website=site, probe=MockAuditProbe(), detector=_detector)
    await db_session.refresh(purchase)
    assert purchase.status is IssueStatus.TODO
    assert purchase.resolved_at is None
