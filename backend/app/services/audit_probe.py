"""Source de signaux d'audit (GA4 / GSC / Core Web Vitals).

`MockAuditProbe` : fixtures alignees avec les mocks frontend.
`RealAuditProbe` : Core Web Vitals reels via PageSpeed Insights (P2) ; GA4 / GSC
restent neutres jusqu'a l'integration GA4 Data API + Search Console (P3).
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from app.models.enums import StackKind
from app.services.pagespeed import (
    CostlyEntity,
    HeavyAsset,
    ShiftElement,
    fetch_pagespeed,
)

if TYPE_CHECKING:
    import httpx

__all__ = [
    "AuditProbe",
    "CostlyEntity",
    "CwvSignals",
    "Ga4Signals",
    "GscSignals",
    "GscUrlSample",
    "HeavyAsset",
    "MockAuditProbe",
    "ProbeData",
    "RealAuditProbe",
    "ShiftElement",
]


@dataclass(frozen=True, slots=True)
class Ga4Signals:
    score: int
    purchase_missing_params: tuple[str, ...] = ()
    missing_events: tuple[str, ...] = ()
    login_missing_user_id: bool = False


@dataclass(frozen=True, slots=True)
class GscUrlSample:
    """URL echantillon Search Console (30 j glissants)."""

    path: str  # chemin relatif, ex. "/collections/vetements-homme"
    status: str  # "Indexee" | "Exclue noindex" | "Redirection 301" | "Decouverte non indexee"
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
            sample_urls=(
                GscUrlSample("/collections/vetements-homme", "Indexée", 320, 8400),
                GscUrlSample("/collections/accessoires", "Indexée", 45, 6200),
                GscUrlSample("/produits/edition-limitee", "Indexée", 5, 5200),
                GscUrlSample("/blog/guide-coton-bio", "Indexée", 210, 3100),
                GscUrlSample("/produits/pull-marin", "Indexée", 88, 1900),
                GscUrlSample("/blog/entretien-laine", "Indexée", 12, 240),
                GscUrlSample("/collections/soldes-ete", "Découverte non indexée", 0, 30),
                GscUrlSample("/produits/vieux-modele-2024", "Redirection 301", 0, 0),
                GscUrlSample("/panier", "Exclue noindex", 0, 0),
            ),
        ),
        cwv=CwvSignals(
            score=61,
            lcp_ms=3400,
            inp_ms=184,
            cls=0.08,
            field_data=True,
            heavy_assets=("hero-banner.jpg", "collection-2026-large.png"),
            blocking_scripts=("theme.css", "fonts.googleapis.com"),
            third_party_scripts=("Google Tag Manager", "Hotjar"),
            js_execution_ms=2100,
            total_blocking_time_ms=640,
            lcp_element='<img class="hero-image" src="/img/hero-banner.jpg">',
            costly_entities=(
                CostlyEntity("Google Tag Manager", "Tag manager", 480, 210),
                CostlyEntity("Hotjar", "Enregistrement de session", 260, 140),
            ),
            lcp_assets=(
                HeavyAsset("hero-banner.jpg", "JPEG", 1801, 1367),
                HeavyAsset("collection-2026-large.png", "PNG", 898, 586),
            ),
            shift_elements=(
                ShiftElement(
                    "section.hero > img.hero-image",
                    0.05,
                    "Visuel d'accueil sans width/height : l'espace se reserve apres chargement.",
                ),
                ShiftElement(
                    "div.promo-bar",
                    0.03,
                    "Bandeau promo injecte apres l'hydratation, pousse le contenu.",
                ),
            ),
        ),
    ),
    _Fixture(
        domains=("atelier-nord.com",),
        ga4=Ga4Signals(score=64, missing_events=("generate_lead",)),
        gsc=GscSignals(
            score=0,
            connection_stale_days=6,
            sample_urls=(
                GscUrlSample("/realisations/cuisine-chene", "Indexée", 64, 1500),
                GscUrlSample("/realisations/bibliotheque-sur-mesure", "Indexée", 40, 980),
                GscUrlSample("/blog/choisir-son-bois", "Indexée", 18, 620),
                GscUrlSample("/services/pose", "Découverte non indexée", 0, 45),
                GscUrlSample("/realisations/ancienne-galerie", "Redirection 301", 0, 0),
                GscUrlSample("/devis", "Exclue noindex", 0, 0),
            ),
        ),
        cwv=CwvSignals(
            score=73,
            lcp_ms=2100,
            inp_ms=212,
            cls=0.18,
            field_data=True,
            heavy_assets=("banner-workshop.jpg",),
            blocking_scripts=("app.css",),
            third_party_scripts=("Filtres produit (bundle interne)", "Google Tag Manager"),
            js_execution_ms=1450,
            total_blocking_time_ms=410,
            lcp_element='<h1 class="page-title">Atelier Nord</h1>',
            costly_entities=(
                CostlyEntity("Filtres produit (bundle interne)", "Script applicatif", 320, 180),
                CostlyEntity("Google Tag Manager", "Tag manager", 190, 90),
            ),
            lcp_assets=(HeavyAsset("banner-workshop.jpg", "JPEG", 540, 360),),
            shift_elements=(
                ShiftElement(
                    "div.consent-banner",
                    0.12,
                    "Banniere de consentement sans reserve d'espace, inseree en haut de page.",
                ),
                ShiftElement(
                    "img.product-thumb",
                    0.04,
                    "Vignettes produit sans dimensions explicites.",
                ),
            ),
        ),
    ),
    _Fixture(
        domains=("studiolumen.io",),
        ga4=Ga4Signals(score=88),
        gsc=GscSignals(
            score=95,
            valid_pages=142,
            excluded_pages=7,
            sample_urls=(
                GscUrlSample("/blog/design-system-2026", "Indexée", 340, 4200),
                GscUrlSample("/fonctionnalites", "Indexée", 260, 5400),
                GscUrlSample("/tarifs", "Indexée", 95, 7800),
                GscUrlSample("/docs/demarrage", "Indexée", 70, 1100),
                GscUrlSample("/demo", "Découverte non indexée", 0, 60),
                GscUrlSample("/old-pricing", "Redirection 301", 0, 0),
                GscUrlSample("/legal/cgu", "Exclue noindex", 0, 0),
            ),
        ),
        cwv=CwvSignals(
            score=79,
            lcp_ms=1900,
            inp_ms=260,
            cls=0.04,
            field_data=True,
            third_party_scripts=("Table de prix (hydratation React)", "Intercom"),
            js_execution_ms=1980,
            total_blocking_time_ms=520,
            lcp_element='<img class="case-study-cover" src="/media/lumen-cover.avif">',
            costly_entities=(
                CostlyEntity("Table de prix (hydratation React)", "Script applicatif", 610, 280),
                CostlyEntity("Intercom", "Chat support", 240, 110),
            ),
            shift_elements=(
                ShiftElement(
                    "table.pricing-grid",
                    0.03,
                    "La table de prix se redimensionne a l'hydratation sur /tarifs.",
                ),
            ),
        ),
    ),
    _Fixture(
        domains=("cap-horizon.co",),
        ga4=Ga4Signals(score=71, login_missing_user_id=True),
        gsc=GscSignals(
            score=84,
            valid_pages=168,
            excluded_pages=32,
            sample_urls=(
                GscUrlSample("/destinations/islande", "Indexée", 180, 4900),
                GscUrlSample("/blog/preparer-trek-hiver", "Indexée", 140, 2600),
                GscUrlSample("/destinations/patagonie", "Indexée", 30, 5100),
                GscUrlSample("/a-propos", "Indexée", 8, 190),
                GscUrlSample("/offres/derniere-minute", "Découverte non indexée", 0, 80),
                GscUrlSample("/destinations/norvege-2024", "Redirection 301", 0, 0),
                GscUrlSample("/reserver", "Exclue noindex", 0, 0),
            ),
        ),
        cwv=CwvSignals(
            score=58,
            lcp_ms=4100,
            inp_ms=240,
            cls=0.06,
            field_data=True,
            heavy_assets=("app-main.js", "slide-01.jpg"),
            blocking_scripts=("app-main.js",),
            third_party_scripts=("Bundle applicatif (montage des vues)", "Google Tag Manager"),
            js_execution_ms=2450,
            total_blocking_time_ms=700,
            lcp_element='<div class="hero-carousel" data-slide="1"></div>',
            costly_entities=(
                CostlyEntity("Bundle applicatif (montage des vues)", "Script applicatif", 890, 360),
                CostlyEntity("Google Tag Manager", "Tag manager", 210, 95),
            ),
            lcp_assets=(
                HeavyAsset("app-main.js", "JS", 1904, 0),
                HeavyAsset("slide-01.jpg", "JPEG", 720, 470),
            ),
            shift_elements=(
                ShiftElement(
                    "div.hero-carousel",
                    0.04,
                    "Le carrousel n'a pas de hauteur reservee avant initialisation JS.",
                ),
            ),
        ),
    ),
]

_NEUTRAL = _Fixture(
    ga4=Ga4Signals(score=55),
    gsc=GscSignals(
        score=60,
        valid_pages=40,
        excluded_pages=6,
        sample_urls=(
            GscUrlSample("/", "Indexée", 120, 3200),
            GscUrlSample("/services", "Indexée", 24, 900),
            GscUrlSample("/blog/premier-article", "Indexée", 6, 210),
            GscUrlSample("/mentions-legales", "Exclue noindex", 0, 0),
        ),
    ),
    cwv=CwvSignals(score=70, lcp_ms=2300, inp_ms=180, cls=0.05),
)


class MockAuditProbe(AuditProbe):
    async def collect(self, *, domain: str, stack: StackKind) -> ProbeData:
        _ = stack
        key = domain.lower().removeprefix("www.")
        fixture = next((f for f in _FIXTURES if key in f.domains), _NEUTRAL)
        return ProbeData(ga4=fixture.ga4, gsc=fixture.gsc, cwv=fixture.cwv)


class RealAuditProbe(AuditProbe):
    """Core Web Vitals via PageSpeed Insights. GA4 / GSC : signaux neutres
    (score 0) jusqu'a l'integration GA4 Data API + Search Console (P3)."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._api_key = api_key or None
        self._client = client

    async def collect(self, *, domain: str, stack: StackKind) -> ProbeData:
        _ = stack
        cwv_kwargs = await fetch_pagespeed(domain, api_key=self._api_key, client=self._client)
        return ProbeData(
            ga4=Ga4Signals(score=0),
            gsc=GscSignals(score=0),
            cwv=CwvSignals(**cwv_kwargs),
        )
