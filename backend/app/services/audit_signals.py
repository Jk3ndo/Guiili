"""Types de signaux d'audit — partages par les sondes (`pagespeed`, `gsc`,
`ga4`), l'assemblage (`audit_probe`) et le moteur de regles (`audit_engine`).

Isole ici pour eviter tout cycle d'import : les modules de sonde importent ces
types, `audit_probe` importe les sondes, jamais l'inverse.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Ga4Signals:
    score: int
    purchase_missing_params: tuple[str, ...] = ()
    missing_events: tuple[str, ...] = ()
    login_missing_user_id: bool = False
    # True = l'appel GA4 Data API a echoue (token revoque / quota) : signaux a 0.
    degraded: bool = False


@dataclass(frozen=True, slots=True)
class GscUrlSample:
    """URL echantillon Search Console (30 j glissants)."""

    path: str  # chemin relatif, ex. "/collections/vetements-homme"
    status: str  # "Indexée" | "Exclue noindex" | "Redirection 301" | "Découverte non indexée"
    clicks: int
    impressions: int


@dataclass(frozen=True, slots=True)
class GscSignals:
    score: int
    valid_pages: int = 0
    excluded_pages: int = 0
    noindex_pages: int = 0
    noindex_on_products: bool = False
    connection_stale_days: int = 0
    sample_urls: tuple[GscUrlSample, ...] = ()
    # True = l'appel Search Console a echoue (token revoque / quota) : signaux a 0.
    degraded: bool = False


@dataclass(frozen=True, slots=True)
class CostlyEntity:
    """Acteur tiers qui occupe le thread principal (diagnostic INP)."""

    name: str
    category: str
    main_thread_ms: int
    blocking_ms: int


@dataclass(frozen=True, slots=True)
class HeavyAsset:
    """Image non optimisée pesant sur le LCP."""

    name: str
    current_format: str
    size_kb: int
    estimated_saving_kb: int


@dataclass(frozen=True, slots=True)
class ShiftElement:
    """Nœud DOM responsable d'un décalage de mise en page (diagnostic CLS)."""

    selector: str
    impact: float
    note: str


@dataclass(frozen=True, slots=True)
class CwvSignals:
    score: int
    lcp_ms: int = 0
    inp_ms: int = 0
    cls: float = 0.0
    # Diagnostics PageSpeed (vides = pas de rapport / mode degrade).
    heavy_assets: tuple[str, ...] = ()  # images / JS non optimises
    blocking_scripts: tuple[str, ...] = ()  # ressources bloquant le rendu
    third_party_scripts: tuple[str, ...] = ()  # entites tierces couteuses (INP)
    js_execution_ms: int = 0
    total_blocking_time_ms: int = 0
    lcp_element: str | None = None
    field_data: bool = False  # True = CrUX terrain, False = labo / degrade
    # Diagnostics structures (INP / LCP / CLS).
    costly_entities: tuple[CostlyEntity, ...] = ()
    lcp_assets: tuple[HeavyAsset, ...] = ()
    shift_elements: tuple[ShiftElement, ...] = ()


@dataclass(frozen=True, slots=True)
class ProbeData:
    ga4: Ga4Signals
    gsc: GscSignals
    cwv: CwvSignals
