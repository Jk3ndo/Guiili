# backend/app/services/measurement/event_snippets.py
"""Snippets d'instrumentation `dataLayer.push` pour les événements du catalogue.

`purchase` et `generate_lead` réutilisent la bibliothèque par stack ; les autres
événements sont fournis en JavaScript générique (à adapter au framework par
l'utilisateur, c'est dit dans les instructions).
"""

from __future__ import annotations

from dataclasses import dataclass

from app.models.enums import StackKind
from app.services.snippet_library import SnippetEvent, get_snippets


@dataclass(frozen=True, slots=True)
class ItemSnippet:
    language: str
    code: str
    target_path: str
    instructions: str


_GENERIC_NOTE = (
    "Snippet JavaScript générique : adapte-le à ton framework (composant, hook, "
    "gestionnaire d'événement) ou transmets-le à ton développeur."
)

_ECOM = """// À déclencher __WHEN__
window.dataLayer = window.dataLayer || [];
window.dataLayer.push({ ecommerce: null });
window.dataLayer.push({
  event: "__EVENT__",
  ecommerce: {
    currency: "EUR",
    value: 0, // montant total concerné
    items: [
      { item_id: "SKU123", item_name: "Nom du produit", price: 0, quantity: 1 },
    ],
  },
});
"""

_SIMPLE = """// À déclencher __WHEN__
window.dataLayer = window.dataLayer || [];
window.dataLayer.push({
  event: "__EVENT__",__PARAMS__
});
"""

_LINK = """// À charger sur toutes les pages
document.addEventListener("click", (e) => {
  const link = e.target.closest('__SELECTOR__');
  if (!link) return;
  window.dataLayer = window.dataLayer || [];
  window.dataLayer.push({ event: "__EVENT__", link_url: link.href });
});
"""

_CONSENT = """// À placer AVANT le snippet Google Tag Manager, dans le <head>
window.dataLayer = window.dataLayer || [];
function gtag() { dataLayer.push(arguments); }
gtag('consent', 'default', {
  ad_storage: 'denied',
  ad_user_data: 'denied',
  ad_personalization: 'denied',
  analytics_storage: 'denied',
  wait_for_update: 500,
});
// Ta bannière de consentement doit ensuite appeler gtag('consent', 'update', {...})
// quand le visiteur accepte.
"""

_ECOM_WHEN = {
    "view_item": "au chargement d'une fiche produit",
    "add_to_cart": "au clic sur « ajouter au panier »",
    "begin_checkout": "à l'ouverture de la page de paiement",
}

_SIMPLE_EVENTS: dict[str, tuple[str, str]] = {
    "sign_up": ("après la création réussie du compte", '\n  method: "email", // ou "google", …'),
    "login": ("après une connexion réussie", '\n  method: "email",'),
    "begin_trial": ("au démarrage effectif de l'essai", '\n  plan: "pro", // nom de l\'offre'),
    "subscribe": (
        "après la souscription à une offre payante",
        '\n  value: 0, // montant de l\'abonnement\n  currency: "EUR",',
    ),
    "tutorial_complete": ("quand l'utilisateur termine l'onboarding", ""),
    "newsletter_signup": ("après l'inscription réussie à la newsletter", ""),
    "share": (
        "au clic sur un bouton de partage",
        '\n  method: "twitter", // réseau utilisé\n  content_type: "article",',
    ),
}

_LINK_EVENTS: dict[str, str] = {
    "click_to_call": 'a[href^="tel:"]',
    "click_email": 'a[href^="mailto:"]',
    "click_whatsapp": 'a[href*="wa.me"], a[href*="whatsapp.com"]',
}


def _from_library(event: SnippetEvent, stack: StackKind | None) -> ItemSnippet | None:
    entries = get_snippets(stack, event)
    if not entries:
        return None
    first = entries[0]
    return ItemSnippet(first.language, first.code, first.target_path, first.instructions)


def snippet_for_event(event: str, stack: StackKind | None) -> ItemSnippet | None:
    if event == "purchase":
        return _from_library(SnippetEvent.PURCHASE, stack)
    if event == "generate_lead":
        return _from_library(SnippetEvent.LEAD, stack)
    if event in _ECOM_WHEN:
        code = _ECOM.replace("__WHEN__", _ECOM_WHEN[event]).replace("__EVENT__", event)
        return ItemSnippet("js", code, "assets/analytics.js", _GENERIC_NOTE)
    if event in _SIMPLE_EVENTS:
        when, params = _SIMPLE_EVENTS[event]
        code = (
            _SIMPLE.replace("__WHEN__", when)
            .replace("__EVENT__", event)
            .replace("__PARAMS__", params)
        )
        return ItemSnippet("js", code, "assets/analytics.js", _GENERIC_NOTE)
    if event in _LINK_EVENTS:
        code = _LINK.replace("__SELECTOR__", _LINK_EVENTS[event]).replace("__EVENT__", event)
        return ItemSnippet(
            "js",
            code,
            "assets/analytics.js",
            "À charger une seule fois sur toutes les pages du site. " + _GENERIC_NOTE,
        )
    if event == "consent_default":
        return ItemSnippet(
            "js",
            _CONSENT,
            "<head> (avant le snippet GTM)",
            "À placer avant le snippet Google Tag Manager. Si ta bannière de consentement "
            "envoie déjà cet état par défaut, ne l'ajoute pas en double.",
        )
    return None
