from app.models.enums import StackKind
from app.services.measurement.site_types import detect_site_types, resolve_effective_types

_SHOP = """
<html><head><script type="application/ld+json">{"@type": "Product", "name": "T-shirt"}</script>
<script src="https://cdn.shopify.com/s/files/app.js"></script></head>
<body><button class="add-to-cart">Ajouter au panier</button><a href="/cart">Panier</a></body></html>
"""
_LEADS = """
<html><body><h1>Plombier à Lyon</h1><a href="tel:+33400000000">Appeler</a>
<form action="/contact"><input name="email"></form><p>Demandez un devis gratuit</p></body></html>
"""
_SAAS = """
<html><body><a href="/pricing">Tarifs</a><a href="/login">Connexion</a>
<button>Essai gratuit</button><a href="/signup">Créer un compte</a></body></html>
"""
_BLOG = """
<html><head><script type="application/ld+json">{"@type": "BlogPosting"}</script></head>
<body><article><h1>Mon article</h1></article><a href="/blog">Blog</a></body></html>
"""


def _types(html: str, stack: StackKind | None = None) -> list[str]:
    return [g["type"] for g in detect_site_types(html, stack)]


def test_ecommerce_is_detected_first() -> None:
    guesses = detect_site_types(_SHOP)
    assert guesses[0]["type"] == "ecommerce"
    assert guesses[0]["confidence"] >= 0.8
    assert guesses[0]["signals"]


def test_lead_gen_saas_and_content_are_detected() -> None:
    assert _types(_LEADS)[0] == "lead_gen"
    assert _types(_SAAS)[0] == "saas"
    assert _types(_BLOG)[0] == "content"


def test_woocommerce_stack_alone_counts_as_ecommerce() -> None:
    assert _types("<html><body>Bienvenue</body></html>", StackKind.WOOCOMMERCE)[0] == "ecommerce"


def test_multiple_types_can_be_returned() -> None:
    both = _SHOP.replace("</body>", '<article>x</article><a href="/blog">Blog</a></body>')
    types = _types(both)
    assert "ecommerce" in types and "content" in types


def test_unknown_site_falls_back_to_other() -> None:
    guesses = detect_site_types("<html><body>Bonjour</body></html>")
    assert [g["type"] for g in guesses] == ["other"]
    assert guesses[0]["confidence"] == 0.5


def test_confidence_is_capped_at_one() -> None:
    assert all(g["confidence"] <= 1.0 for g in detect_site_types(_SHOP * 3))


def test_resolve_effective_types() -> None:
    detected = [
        {"type": "ecommerce", "confidence": 0.8, "signals": []},
        {"type": "content", "confidence": 0.35, "signals": []},
    ]
    assert resolve_effective_types(detected, ["saas", "lead_gen"]) == ["saas", "lead_gen"]
    assert resolve_effective_types(detected, None) == ["ecommerce"]
    weak = [{"type": "content", "confidence": 0.35, "signals": []}]
    assert resolve_effective_types(weak, None) == ["content"]
    assert resolve_effective_types([], None) == ["other"]
    assert resolve_effective_types([{"type": "other", "confidence": 0.5, "signals": []}], None) == [
        "other"
    ]
