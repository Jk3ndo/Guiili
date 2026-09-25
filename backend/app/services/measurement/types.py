from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

Layer = Literal["foundations", "events", "conversions", "ads", "seo"]
SiteType = Literal["ecommerce", "lead_gen", "saas", "content", "other"]
State = Literal[
    "unknown",
    "missing",
    "on_page",
    "received",
    "unverifiable",
    "not_applicable",
    "dismissed",
]
Level = Literal["on_page", "received"]
ActionKind = Literal["guide", "snippet", "gtm_container", "advisor", "pr"]

SITE_TYPES: tuple[SiteType, ...] = ("ecommerce", "lead_gen", "saas", "content", "other")

CHECK_KINDS: frozenset[str] = frozenset(
    {
        "gtm_installed",
        "gtm_in_head",
        "ga4_tag",
        "no_double",
        "consent",
        "datalayer",
        "event",
        "purchase_params",
        "key_events",
        "key_events_value",
        "ads_link",
        "ads_conversion_tag",
        "manual",
        "gsc_linked",
        "gsc_sitemaps",
        "robots",
        "tls",
    }
)


@dataclass(frozen=True, slots=True)
class MeasurementItem:
    id: str
    layer: Layer
    # None = tous les sites ; sinon ensemble de types concernés.
    applies_to: frozenset[SiteType] | None
    weight: int  # 1..100, plus grand = plus prioritaire
    quick_win: bool
    title: str
    why: str  # explication novice, en français
    check: str  # une valeur de CHECK_KINDS
    arg: str | None  # ex. nom de l'événement pour check == "event"
    max_level: Level  # plus haut niveau de preuve atteignable
    guide: tuple[str, ...]
    actions: tuple[ActionKind, ...]
    snippet_event: str | None = None


@dataclass(frozen=True, slots=True)
class Outcome:
    state: State
    evidence: dict[str, Any] = field(default_factory=dict)
    reason: str | None = None
