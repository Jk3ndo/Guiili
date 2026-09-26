"""Détection heuristique du type de site (fonction pure, testée sur des fixtures HTML)."""

from __future__ import annotations

import re
from typing import Any

from app.models.enums import StackKind

_JSONLD_TYPE = re.compile(r'"@type"\s*:\s*"([A-Za-z]+)"')
_MIN_CONFIDENCE = 0.3
_PICK_CONFIDENCE = 0.5

_WORDS_CART = ("add-to-cart", "add_to_cart", "ajouter au panier", "add to cart")
_WORDS_LEAD = (
    "demander un devis",
    "demandez un devis",
    "devis gratuit",
    "contactez-nous",
    "prendre rendez-vous",
    "prendre rdv",
)
_WORDS_SAAS = (
    "essai gratuit",
    "free trial",
    "créer un compte",
    "creer un compte",
    "sign up free",
    "s'inscrire",
)


_SHOPIFY_MARKERS = ("cdn.shopify.com", "myshopify.com", "shopify.theme", "window.shopify")


def _has_href(low: str, *needles: str) -> bool:
    """Lien dont la valeur commence par le motif, suivi d'une frontière (`/`, `?`, `#`,
    guillemet fermant) : `/cart` ne correspond pas à `/carte`."""
    return any(re.search(rf"""href=["']{re.escape(n)}(?=[/?#"'])""", low) for n in needles)


def detect_site_types(html: str, stack: StackKind | None = None) -> list[dict[str, Any]]:
    low = html.lower()
    scores: dict[str, float] = {"ecommerce": 0.0, "lead_gen": 0.0, "saas": 0.0, "content": 0.0}
    signals: dict[str, list[str]] = {key: [] for key in scores}

    def add(kind: str, points: float, why: str) -> None:
        scores[kind] += points
        signals[kind].append(why)

    jsonld = {match.lower() for match in _JSONLD_TYPE.findall(html)}

    # Boutique
    if stack == StackKind.WOOCOMMERCE:
        add("ecommerce", 0.6, "stack WooCommerce")
    if any(marker in low for marker in _SHOPIFY_MARKERS):
        add("ecommerce", 0.6, "Shopify détecté")
    if "product" in jsonld:
        add("ecommerce", 0.35, "données structurées Product")
    if any(word in low for word in _WORDS_CART):
        add("ecommerce", 0.3, "bouton « ajouter au panier »")
    if _has_href(low, "/cart", "/panier", "/checkout"):
        add("ecommerce", 0.2, "lien vers panier ou paiement")

    # Prise de contact
    if "<form" in low:
        add("lead_gen", 0.2, "formulaire présent")
    if 'href="tel:' in low or "href='tel:" in low:
        add("lead_gen", 0.25, "lien téléphone")
    if 'href="mailto:' in low or "href='mailto:" in low:
        add("lead_gen", 0.1, "lien e-mail")
    if any(word in low for word in _WORDS_LEAD):
        add("lead_gen", 0.3, "vocabulaire de devis / contact")

    # SaaS
    if any(word in low for word in _WORDS_SAAS):
        add("saas", 0.3, "essai gratuit ou création de compte")
    if _has_href(low, "/pricing", "/tarifs"):
        add("saas", 0.3, "page de tarifs")
    if _has_href(low, "/login", "/signin", "/connexion"):
        add("saas", 0.2, "page de connexion")

    # Contenu
    if jsonld & {"article", "blogposting", "newsarticle"}:
        add("content", 0.4, "données structurées Article")
    if "<article" in low:
        add("content", 0.2, "balise article")
    if _has_href(low, "/blog"):
        add("content", 0.3, "section blog")

    guesses = [
        {
            "type": kind,
            "confidence": min(1.0, round(score, 2)),
            "signals": signals[kind],
        }
        for kind, score in scores.items()
        if score >= _MIN_CONFIDENCE
    ]
    guesses.sort(key=lambda g: g["confidence"], reverse=True)
    if not guesses:
        return [{"type": "other", "confidence": 0.5, "signals": []}]
    return guesses


def resolve_effective_types(
    detected: list[dict[str, Any]], confirmed: list[str] | None
) -> list[str]:
    """Types utilisés par le plan : la confirmation prime, sinon les types détectés
    avec une confiance suffisante, sinon le meilleur candidat, sinon « other »."""
    if confirmed:
        return list(confirmed)
    picked = [g["type"] for g in detected if g["confidence"] >= _PICK_CONFIDENCE]
    if picked:
        return [t for t in picked if t != "other"] or ["other"]
    if detected and detected[0]["confidence"] >= _MIN_CONFIDENCE and detected[0]["type"] != "other":
        return [detected[0]["type"]]
    return ["other"]
