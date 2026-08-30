"""Bibliotheque de snippets d'instrumentation `dataLayer.push` par framework.

Registre type `(StackKind, SnippetEvent) -> Snippet`. `get_snippets` resout la
famille de stack (Vue / Angular / generic / unknown -> fallback vanilla JS).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from app.models.enums import StackKind


class SnippetEvent(StrEnum):
    PURCHASE = "purchase"
    LEAD = "lead"
    CUSTOM = "custom"


@dataclass(frozen=True, slots=True)
class Snippet:
    language: str  # "ts" | "tsx" | "php" | "js"
    code: str
    target_path: str
    instructions: str


@dataclass(frozen=True, slots=True)
class SnippetEntry:
    stack: StackKind
    event: SnippetEvent
    language: str
    code: str
    target_path: str
    instructions: str


# --------------------------------------------------------------------------- #
#  Next.js (App Router)                                                        #
# --------------------------------------------------------------------------- #

_NEXT_DECLARE = """declare global {
  interface Window {
    dataLayer: Record<string, unknown>[];
  }
}
"""

_NEXT_PURCHASE = f"""// lib/analytics.ts
{_NEXT_DECLARE}
export function trackPurchase(order: {{
  id: string;
  value: number;
  currency: string;
  items: {{ id: string; name: string; price: number; quantity: number }}[];
}}) {{
  window.dataLayer = window.dataLayer ?? [];
  window.dataLayer.push({{ ecommerce: null }});
  window.dataLayer.push({{
    event: "purchase",
    ecommerce: {{
      transaction_id: order.id,
      value: order.value,
      currency: order.currency,
      items: order.items.map((item) => ({{
        item_id: item.id,
        item_name: item.name,
        price: item.price,
        quantity: item.quantity,
      }})),
    }},
  }});
}}
"""

_NEXT_LEAD = """// components/lead-form.tsx
"use client";

import { useState } from "react";

export function LeadForm() {
  const [done, setDone] = useState(false);

  async function onSubmit(formData: FormData) {
    const res = await fetch("/api/lead", { method: "POST", body: formData });
    if (!res.ok) return;

    window.dataLayer = window.dataLayer ?? [];
    window.dataLayer.push({ event: "generate_lead", form_id: "contact" });
    setDone(true);
  }

  return (
    <form action={onSubmit}>
      {/* ... champs ... */}
      <button type="submit" disabled={done}>Envoyer</button>
    </form>
  );
}
"""

_NEXT_CUSTOM = """// lib/analytics.ts
type DataLayerEvent = { event: string } & Record<string, unknown>;

export function trackEvent(payload: DataLayerEvent) {
  window.dataLayer = window.dataLayer ?? [];
  window.dataLayer.push(payload);
}

// exemple
trackEvent({ event: "demo_requested", plan: "pro", source: "pricing" });
"""

# --------------------------------------------------------------------------- #
#  WordPress                                                                   #
# --------------------------------------------------------------------------- #

_WP_PURCHASE = """<?php
// functions.php - evenement purchase sur une page de confirmation generique

add_action( 'wp_footer', function () {
    if ( ! is_page( 'merci' ) ) {
        return;
    }
    $order = cc_get_last_order(); // fourni par votre integration commande
    ?>
    <script>
        window.dataLayer = window.dataLayer || [];
        window.dataLayer.push({ ecommerce: null });
        window.dataLayer.push(<?php echo wp_json_encode( array(
            'event'     => 'purchase',
            'ecommerce' => array(
                'transaction_id' => $order['id'],
                'value'          => (float) $order['total'],
                'currency'       => $order['currency'],
            ),
        ) ); ?>);
    </script>
    <?php
} );
"""

_WP_LEAD = """<?php
// functions.php - evenement generate_lead apres un envoi Contact Form 7

add_action( 'wp_footer', function () {
    ?>
    <script>
        document.addEventListener( 'wpcf7mailsent', function ( event ) {
            window.dataLayer = window.dataLayer || [];
            window.dataLayer.push({
                event: 'generate_lead',
                form_id: 'cf7-' + event.detail.contactFormId,
            });
        } );
    </script>
    <?php
} );
"""

_WP_CUSTOM = """<?php
// functions.php - evenement personnalise via attribut data-track-event

add_action( 'wp_footer', function () {
    ?>
    <script>
        document.querySelectorAll( '[data-track-event]' ).forEach( function ( el ) {
            el.addEventListener( 'click', function () {
                window.dataLayer = window.dataLayer || [];
                window.dataLayer.push({ event: el.dataset.trackEvent });
            } );
        } );
    </script>
    <?php
} );
"""

# --------------------------------------------------------------------------- #
#  WooCommerce (surcharge du purchase)                                         #
# --------------------------------------------------------------------------- #

_WOO_PURCHASE = """<?php
// functions.php - evenement purchase sur la page de confirmation WooCommerce

add_action( 'woocommerce_thankyou', function ( $order_id ) {
    $order = wc_get_order( $order_id );
    if ( ! $order || $order->get_meta( '_cc_purchase_pushed' ) ) {
        return;
    }

    $items = array();
    foreach ( $order->get_items() as $item ) {
        $product = $item->get_product();
        $items[] = array(
            'item_id'   => $product ? $product->get_sku() : (string) $item->get_product_id(),
            'item_name' => $item->get_name(),
            'price'     => (float) $order->get_item_total( $item, false, false ),
            'quantity'  => (int) $item->get_quantity(),
        );
    }
    ?>
    <script>
        window.dataLayer = window.dataLayer || [];
        window.dataLayer.push({ ecommerce: null });
        window.dataLayer.push(<?php echo wp_json_encode( array(
            'event'     => 'purchase',
            'ecommerce' => array(
                'transaction_id' => $order->get_order_number(),
                'value'          => (float) $order->get_total(),
                'currency'       => $order->get_currency(),
                'items'          => $items,
            ),
        ) ); ?>);
    </script>
    <?php
    $order->update_meta_data( '_cc_purchase_pushed', 1 );
    $order->save();
}, 20 );
"""

# --------------------------------------------------------------------------- #
#  Nuxt (composable)                                                           #
# --------------------------------------------------------------------------- #

_NUXT_PURCHASE = """// composables/useAnalytics.ts
export function useAnalytics() {
  function push(payload: Record<string, unknown>) {
    if (import.meta.client) {
      window.dataLayer = window.dataLayer ?? [];
      window.dataLayer.push(payload);
    }
  }

  function trackPurchase(order: {
    id: string;
    value: number;
    currency: string;
    items: { id: string; name: string; price: number; quantity: number }[];
  }) {
    push({ ecommerce: null });
    push({
      event: "purchase",
      ecommerce: {
        transaction_id: order.id,
        value: order.value,
        currency: order.currency,
        items: order.items.map((i) => ({
          item_id: i.id,
          item_name: i.name,
          price: i.price,
          quantity: i.quantity,
        })),
      },
    });
  }

  return { push, trackPurchase };
}
"""

_NUXT_LEAD = """// composables/useAnalytics.ts (extrait)
export function useAnalytics() {
  function push(payload: Record<string, unknown>) {
    if (import.meta.client) {
      window.dataLayer = window.dataLayer ?? [];
      window.dataLayer.push(payload);
    }
  }

  function trackLead(formId: string) {
    push({ event: "generate_lead", form_id: formId });
  }

  return { push, trackLead };
}
"""

_NUXT_CUSTOM = """// composables/useAnalytics.ts (extrait)
export function useAnalytics() {
  function trackEvent(name: string, params: Record<string, unknown> = {}) {
    if (import.meta.client) {
      window.dataLayer = window.dataLayer ?? [];
      window.dataLayer.push({ event: name, ...params });
    }
  }

  return { trackEvent };
}
"""

# --------------------------------------------------------------------------- #
#  Fallback vanilla JS (Vue, Angular, generic, unknown)                        #
# --------------------------------------------------------------------------- #

_JS_PURCHASE = """// assets/analytics.js - a charger sur la page de confirmation

(function () {
  var order = window.__ORDER__; // injecte par le back-end
  if (!order) return;

  window.dataLayer = window.dataLayer || [];
  window.dataLayer.push({ ecommerce: null });
  window.dataLayer.push({
    event: "purchase",
    ecommerce: {
      transaction_id: order.reference,
      value: order.total,
      currency: order.currency,
      items: (order.lines || []).map(function (line) {
        return {
          item_id: line.sku,
          item_name: line.title,
          price: line.unitPrice,
          quantity: line.quantity,
        };
      }),
    },
  });
})();
"""

_JS_LEAD = """// assets/analytics.js

var form = document.querySelector("#lead-form");
if (form) {
  form.addEventListener("submit", function () {
    window.dataLayer = window.dataLayer || [];
    window.dataLayer.push({ event: "generate_lead", form_id: "lead-form" });
  });
}
"""

_JS_CUSTOM = """// assets/analytics.js

function trackEvent(name, params) {
  window.dataLayer = window.dataLayer || [];
  window.dataLayer.push(Object.assign({ event: name }, params || {}));
}

trackEvent("cta_click", { cta_location: "hero" });
"""


def _family(purchase: Snippet, lead: Snippet, custom: Snippet) -> dict[SnippetEvent, Snippet]:
    return {
        SnippetEvent.PURCHASE: purchase,
        SnippetEvent.LEAD: lead,
        SnippetEvent.CUSTOM: custom,
    }


_NEXT_FAMILY = _family(
    Snippet(
        "ts",
        _NEXT_PURCHASE,
        "lib/analytics.ts",
        "Appelez trackPurchase() dans un effet client sur "
        "app/checkout/success/page.tsx, apres confirmation du paiement.",
    ),
    Snippet(
        "tsx",
        _NEXT_LEAD,
        "components/lead-form.tsx",
        "Le push suit la reponse OK de l'API, pas le clic.",
    ),
    Snippet(
        "ts",
        _NEXT_CUSTOM,
        "lib/analytics.ts",
        "Declarez Window.dataLayer une fois, importez trackEvent partout.",
    ),
)

_WP_FAMILY = _family(
    Snippet(
        "php",
        _WP_PURCHASE,
        "wp-content/themes/<theme>/functions.php",
        "Adaptez cc_get_last_order() a votre systeme de commande, ou "
        "utilisez l'extension Code Snippets.",
    ),
    Snippet(
        "php",
        _WP_LEAD,
        "wp-content/themes/<theme>/functions.php",
        "Le hook wpcf7mailsent n'est emis qu'apres l'envoi de l'e-mail.",
    ),
    Snippet(
        "php",
        _WP_CUSTOM,
        "wp-content/themes/<theme>/functions.php",
        'Ajoutez data-track-event="nom_evenement" sur les elements a suivre.',
    ),
)

_WOO_FAMILY = {
    **_WP_FAMILY,
    SnippetEvent.PURCHASE: Snippet(
        "php",
        _WOO_PURCHASE,
        "wp-content/themes/<theme>/functions.php",
        "Le hook woocommerce_thankyou ne se declenche qu'une fois ; le "
        "garde-fou _cc_purchase_pushed evite le double comptage.",
    ),
}

_NUXT_FAMILY = _family(
    Snippet(
        "ts",
        _NUXT_PURCHASE,
        "composables/useAnalytics.ts",
        "Appelez useAnalytics().trackPurchase() sur la page de confirmation.",
    ),
    Snippet(
        "ts",
        _NUXT_LEAD,
        "composables/useAnalytics.ts",
        "Appelez trackLead() dans le callback de succes du formulaire.",
    ),
    Snippet(
        "ts",
        _NUXT_CUSTOM,
        "composables/useAnalytics.ts",
        "import.meta.client garde le push cote navigateur uniquement.",
    ),
)

_FALLBACK_FAMILY = _family(
    Snippet(
        "js",
        _JS_PURCHASE,
        "assets/analytics.js",
        "A charger apres le conteneur GTM, uniquement sur l'URL de confirmation.",
    ),
    Snippet(
        "js",
        _JS_LEAD,
        "assets/analytics.js",
        "Si l'envoi est asynchrone, deplacez le push dans le callback de succes.",
    ),
    Snippet(
        "js",
        _JS_CUSTOM,
        "assets/analytics.js",
        "Exposez trackEvent sur window si d'autres scripts doivent l'appeler.",
    ),
)


_REGISTRY: dict[StackKind, dict[SnippetEvent, Snippet]] = {
    StackKind.NEXTJS: _NEXT_FAMILY,
    StackKind.WORDPRESS: _WP_FAMILY,
    StackKind.WOOCOMMERCE: _WOO_FAMILY,
    StackKind.NUXT: _NUXT_FAMILY,
    StackKind.VUE: _FALLBACK_FAMILY,
    StackKind.ANGULAR: _FALLBACK_FAMILY,
    StackKind.GENERIC: _FALLBACK_FAMILY,
    StackKind.UNKNOWN: _FALLBACK_FAMILY,
}


def _resolve(stack: StackKind | None) -> tuple[StackKind, dict[SnippetEvent, Snippet]]:
    key = stack or StackKind.UNKNOWN
    return key, _REGISTRY.get(key, _FALLBACK_FAMILY)


def get_snippets(stack: StackKind | None, event: SnippetEvent | None = None) -> list[SnippetEntry]:
    resolved_stack, family = _resolve(stack)
    events = [event] if event is not None else list(SnippetEvent)
    return [
        SnippetEntry(
            stack=resolved_stack,
            event=evt,
            language=family[evt].language,
            code=family[evt].code,
            target_path=family[evt].target_path,
            instructions=family[evt].instructions,
        )
        for evt in events
    ]
