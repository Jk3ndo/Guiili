"""Source de signaux d'audit (GA4 / GSC / Core Web Vitals).

P1 : seule l'implementation `MockAuditProbe` existe (fixtures alignees avec les
mocks frontend). `RealAuditProbe` (PageSpeed API + GA4 Data API + GSC) arrive en
P2 — le stub leve `NotImplementedError` pour eviter tout appel silencieux.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field

from app.models.enums import StackKind


@dataclass(frozen=True, slots=True)
class Ga4Signals:
    score: int
    purchase_missing_params: tuple[str, ...] = ()
    missing_events: tuple[str, ...] = ()
    login_missing_user_id: bool = False


@dataclass(frozen=True, slots=True)
class GscSignals:
    score: int
    valid_pages: int = 0
    excluded_pages: int = 0
    noindex_pages: int = 0
    noindex_on_products: bool = False
    connection_stale_days: int = 0


@dataclass(frozen=True, slots=True)
class CwvSignals:
    score: int
    lcp_ms: int = 0
    inp_ms: int = 0
    cls: float = 0.0


@dataclass(frozen=True, slots=True)
class ProbeData:
    ga4: Ga4Signals
    gsc: GscSignals
    cwv: CwvSignals


class AuditProbe(abc.ABC):
    @abc.abstractmethod
    async def collect(self, *, domain: str, stack: StackKind) -> ProbeData: ...


@dataclass(frozen=True, slots=True)
class _Fixture:
    ga4: Ga4Signals
    gsc: GscSignals
    cwv: CwvSignals
    domains: tuple[str, ...] = field(default_factory=tuple)


_FIXTURES: list[_Fixture] = [
    _Fixture(
        domains=("boutique-verte.fr",),
        ga4=Ga4Signals(score=92, purchase_missing_params=("value", "currency")),
        gsc=GscSignals(
            score=78,
            valid_pages=214,
            excluded_pages=37,
            noindex_pages=12,
            noindex_on_products=True,
        ),
        cwv=CwvSignals(score=61, lcp_ms=3400, inp_ms=184, cls=0.08),
    ),
    _Fixture(
        domains=("atelier-nord.com",),
        ga4=Ga4Signals(score=64, missing_events=("generate_lead",)),
        gsc=GscSignals(score=0, connection_stale_days=6),
        cwv=CwvSignals(score=73, lcp_ms=2100, inp_ms=212, cls=0.18),
    ),
    _Fixture(
        domains=("studiolumen.io",),
        ga4=Ga4Signals(score=88),
        gsc=GscSignals(score=95, valid_pages=142, excluded_pages=7),
        cwv=CwvSignals(score=79, lcp_ms=1900, inp_ms=260, cls=0.04),
    ),
    _Fixture(
        domains=("cap-horizon.co",),
        ga4=Ga4Signals(score=71, login_missing_user_id=True),
        gsc=GscSignals(score=84, valid_pages=168, excluded_pages=32),
        cwv=CwvSignals(score=58, lcp_ms=4100, inp_ms=240, cls=0.06),
    ),
]

_NEUTRAL = _Fixture(
    ga4=Ga4Signals(score=55),
    gsc=GscSignals(score=60, valid_pages=40, excluded_pages=6),
    cwv=CwvSignals(score=70, lcp_ms=2300, inp_ms=180, cls=0.05),
)


class MockAuditProbe(AuditProbe):
    async def collect(self, *, domain: str, stack: StackKind) -> ProbeData:
        _ = stack
        key = domain.lower().removeprefix("www.")
        fixture = next((f for f in _FIXTURES if key in f.domains), _NEUTRAL)
        return ProbeData(ga4=fixture.ga4, gsc=fixture.gsc, cwv=fixture.cwv)


class RealAuditProbe(AuditProbe):
    async def collect(self, *, domain: str, stack: StackKind) -> ProbeData:
        raise NotImplementedError("RealAuditProbe (PageSpeed + GA4 Data API + GSC) arrive en P2")
