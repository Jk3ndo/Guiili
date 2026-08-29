import type { StackId, Workspace } from "./types";

/**
 * Stand-in for `GET /api/workspaces/:id/gtm-export`. The container payload and
 * the snippet library are static here; when the API lands, only this file
 * changes. Snippet code is authored with final indentation — it is copied
 * verbatim by the user.
 */

/* -------------------------------------------------------------------------- */
/*  A. GTM container export                                                  */
/* -------------------------------------------------------------------------- */

export type GtmElementKind = "tag" | "trigger" | "variable";

export interface GtmElement {
  kind: GtmElementKind;
  name: string;
  /** One-line description of what it does, shown under the name. */
  detail: string;
}

/** The elements bundled in the exported container, for the synthesis card. */
export const EXPORT_ELEMENTS: GtmElement[] = [
  {
    kind: "tag",
    name: "GA4 Configuration",
    detail: "Balise Google (googtag) — chargée sur toutes les pages",
  },
  {
    kind: "tag",
    name: "GA4 Event — purchase",
    detail: "Événement e-commerce, données lues depuis le dataLayer",
  },
  {
    kind: "tag",
    name: "GA4 Event — generate_lead",
    detail: "Événement de génération de lead (formulaires)",
  },
  {
    kind: "trigger",
    name: "Historique SPA (History Change)",
    detail: "Pages vues sur les apps single-page (Next.js, Vue, Angular)",
  },
  {
    kind: "trigger",
    name: "CE — purchase / generate_lead",
    detail: "Déclencheurs sur événements personnalisés du dataLayer",
  },
  {
    kind: "variable",
    name: "DLV — ecommerce / form_id",
    detail: "Variables de couche de données (version 2)",
  },
];

export interface ImportStep {
  title: string;
  detail: string;
}

/** The 4-step import walkthrough. */
export const IMPORT_STEPS: ImportStep[] = [
  {
    title: "Ouvrir le conteneur dans GTM",
    detail:
      "Téléchargez le fichier JSON ci-dessus, puis ouvrez votre conteneur sur tagmanager.google.com.",
  },
  {
    title: "Administration › Importer un conteneur",
    detail:
      "Onglet Administration, section Conteneur : cliquez sur « Importer un conteneur » et sélectionnez le fichier téléchargé.",
  },
  {
    title: "Espace de travail et mode de fusion",
    detail:
      "Choisissez « Nouveau », puis les options « Fusionner » et « Renommer les conflits » — rien de votre configuration existante n'est écrasé.",
  },
  {
    title: "Prévisualiser puis publier",
    detail:
      "Remplacez l'ID G-XXXXXXXXXX par votre ID de flux GA4, vérifiez le déclenchement en mode Aperçu sur le site, puis publiez la version.",
  },
];

interface ContainerRef {
  accountId: string;
  containerId: string;
  publicId: string;
}

const CONTAINERS: Record<string, ContainerRef> = {
  ws_boutique_verte: {
    accountId: "6012840193",
    containerId: "198765432",
    publicId: "GTM-PK2X9QM",
  },
  ws_atelier_nord: {
    accountId: "6009114772",
    containerId: "201553108",
    publicId: "GTM-T7R4WZ2",
  },
  ws_studio_lumen: {
    accountId: "6014028801",
    containerId: "205991640",
    publicId: "GTM-9LMN3KD",
  },
  ws_cap_horizon: {
    accountId: "6011760554",
    containerId: "209844217",
    publicId: "GTM-CH5PQ8V",
  },
};

const FALLBACK_CONTAINER: ContainerRef = CONTAINERS.ws_boutique_verte;

export function containerRef(workspace: Workspace): ContainerRef {
  return CONTAINERS[workspace.id] ?? FALLBACK_CONTAINER;
}

/** Fixed so the exported file is byte-stable between downloads. */
const FINGERPRINT = "1756450800000";
const EXPORT_TIME = "2026-08-29 09:00:00";

/**
 * Builds a container that GTM's "Import Container" accepts as-is
 * (exportFormatVersion 2, GA4 tags wired to custom-event triggers).
 */
export function buildGtmContainer(workspace: Workspace): Record<string, unknown> {
  const { accountId, containerId, publicId } = containerRef(workspace);
  const base = { accountId, containerId };
  const versionPath = `accounts/${accountId}/containers/${containerId}/versions/0`;
  const managerUrl = `https://tagmanager.google.com/#/container/accounts/${accountId}/containers/${containerId}/workspaces?apiLink=container`;

  return {
    exportFormatVersion: 2,
    exportTime: EXPORT_TIME,
    containerVersion: {
      path: versionPath,
      ...base,
      containerVersionId: "0",
      name: "Control Center — instrumentation GA4",
      description:
        "Généré par Control Center. Import : Administration › Importer un conteneur › Fusionner.",
      container: {
        path: `accounts/${accountId}/containers/${containerId}`,
        ...base,
        name: workspace.domain,
        publicId,
        usageContext: ["WEB"],
        fingerprint: FINGERPRINT,
        tagManagerUrl: managerUrl,
        features: {
          supportUserPermissions: true,
          supportEnvironments: true,
          supportWorkspaces: true,
          supportGtagConfigs: true,
        },
      },
      tag: [
        {
          ...base,
          tagId: "1",
          name: "GA4 Configuration",
          type: "googtag",
          parameter: [
            { type: "template", key: "tagId", value: "G-XXXXXXXXXX" },
            {
              type: "list",
              key: "configSettingsTable",
              list: [
                {
                  type: "map",
                  map: [
                    {
                      type: "template",
                      key: "parameter",
                      value: "send_page_view",
                    },
                    { type: "template", key: "parameterValue", value: "true" },
                  ],
                },
              ],
            },
          ],
          fingerprint: FINGERPRINT,
          firingTriggerId: ["2147479553", "12"],
          tagFiringOption: "oncePerEvent",
          monitoringMetadata: { type: "map" },
          consentSettings: { consentStatus: "notSet" },
        },
        {
          ...base,
          tagId: "2",
          name: "GA4 Event — purchase",
          type: "gaawe",
          parameter: [
            { type: "template", key: "eventName", value: "purchase" },
            { type: "boolean", key: "sendEcommerceData", value: "true" },
            {
              type: "template",
              key: "getEcommerceDataFrom",
              value: "dataLayer",
            },
            {
              type: "tagReference",
              key: "measurementId",
              value: "GA4 Configuration",
            },
          ],
          fingerprint: FINGERPRINT,
          firingTriggerId: ["10"],
          tagFiringOption: "oncePerEvent",
          consentSettings: { consentStatus: "notSet" },
        },
        {
          ...base,
          tagId: "3",
          name: "GA4 Event — generate_lead",
          type: "gaawe",
          parameter: [
            { type: "template", key: "eventName", value: "generate_lead" },
            {
              type: "list",
              key: "eventParameters",
              list: [
                {
                  type: "map",
                  map: [
                    { type: "template", key: "name", value: "form_id" },
                    {
                      type: "template",
                      key: "value",
                      value: "{{DLV - form_id}}",
                    },
                  ],
                },
              ],
            },
            {
              type: "tagReference",
              key: "measurementId",
              value: "GA4 Configuration",
            },
          ],
          fingerprint: FINGERPRINT,
          firingTriggerId: ["11"],
          tagFiringOption: "oncePerEvent",
          consentSettings: { consentStatus: "notSet" },
        },
      ],
      trigger: [
        {
          ...base,
          triggerId: "10",
          name: "CE — purchase",
          type: "customEvent",
          customEventFilter: [
            {
              type: "equals",
              parameter: [
                { type: "template", key: "arg0", value: "{{_event}}" },
                { type: "template", key: "arg1", value: "purchase" },
              ],
            },
          ],
          fingerprint: FINGERPRINT,
        },
        {
          ...base,
          triggerId: "11",
          name: "CE — generate_lead",
          type: "customEvent",
          customEventFilter: [
            {
              type: "equals",
              parameter: [
                { type: "template", key: "arg0", value: "{{_event}}" },
                { type: "template", key: "arg1", value: "generate_lead" },
              ],
            },
          ],
          fingerprint: FINGERPRINT,
        },
        {
          ...base,
          triggerId: "12",
          name: "History Change — SPA",
          type: "historyChange",
          fingerprint: FINGERPRINT,
        },
      ],
      variable: [
        {
          ...base,
          variableId: "1",
          name: "DLV - ecommerce",
          type: "v",
          parameter: [
            { type: "integer", key: "dataLayerVersion", value: "2" },
            { type: "boolean", key: "setDefaultValue", value: "false" },
            { type: "template", key: "name", value: "ecommerce" },
          ],
          fingerprint: FINGERPRINT,
        },
        {
          ...base,
          variableId: "2",
          name: "DLV - form_id",
          type: "v",
          parameter: [
            { type: "integer", key: "dataLayerVersion", value: "2" },
            { type: "boolean", key: "setDefaultValue", value: "true" },
            { type: "template", key: "defaultValue", value: "(not set)" },
            { type: "template", key: "name", value: "form_id" },
          ],
          fingerprint: FINGERPRINT,
        },
      ],
      builtInVariable: [
        { ...base, type: "pageUrl", name: "Page URL" },
        { ...base, type: "pageHostname", name: "Page Hostname" },
        { ...base, type: "pagePath", name: "Page Path" },
        { ...base, type: "referrer", name: "Referrer" },
        { ...base, type: "event", name: "Event" },
        { ...base, type: "historySource", name: "History Source" },
        { ...base, type: "newHistoryFragment", name: "New History Fragment" },
        { ...base, type: "oldHistoryFragment", name: "Old History Fragment" },
      ],
      fingerprint: FINGERPRINT,
      tagManagerUrl: managerUrl,
    },
  };
}

/* -------------------------------------------------------------------------- */
/*  B. Application snippet library                                           */
/* -------------------------------------------------------------------------- */

export type GtmStackId = "nextjs" | "wordpress" | "vanilla";
export type GtmEventId = "purchase" | "lead" | "custom";
export type SnippetLang = "ts" | "tsx" | "js" | "php";

export interface StackOption {
  id: GtmStackId;
  label: string;
}

export interface EventOption {
  id: GtmEventId;
  label: string;
}

export const GTM_STACKS: StackOption[] = [
  { id: "nextjs", label: "Next.js (App Router)" },
  { id: "wordpress", label: "WordPress / WooCommerce" },
  { id: "vanilla", label: "Vanilla JS" },
];

export const GTM_EVENTS: EventOption[] = [
  { id: "purchase", label: "Achat e-commerce (Purchase)" },
  { id: "lead", label: "Soumission de lead" },
  { id: "custom", label: "Événement personnalisé" },
];

export interface Snippet {
  stack: GtmStackId;
  event: GtmEventId;
  lang: SnippetLang;
  /** Path shown in the code block header. */
  filename: string;
  code: string;
  /** Exact path where the snippet belongs. */
  location: string;
  /** One or two sentences on how/when to wire it. */
  locationNote: string;
}

export function snippetKey(stack: GtmStackId, event: GtmEventId): string {
  return `${stack}:${event}`;
}

/** One syntax-highlighted token — plain data, safe across the RSC boundary. */
export interface CodeToken {
  content: string;
  color?: string;
  /** shiki FontStyle bitfield: 1 italic, 2 bold, 4 underline. */
  fontStyle?: number;
}

/** Server-tokenised snippets, keyed by `snippetKey`. One entry per line. */
export type HighlightedSnippets = Record<string, CodeToken[][]>;

/** Maps a detected workspace stack onto the closest snippet family. */
export function gtmStackForWorkspace(stack: StackId): GtmStackId {
  if (stack === "nextjs") return "nextjs";
  if (stack === "wordpress") return "wordpress";
  return "vanilla";
}

const NEXT_PURCHASE = `// lib/analytics.ts
declare global {
  interface Window {
    dataLayer: Record<string, unknown>[];
  }
}

type PurchaseItem = { id: string; name: string; price: number; quantity: number };

type Purchase = {
  transactionId: string;
  value: number;
  currency: string;
  items: PurchaseItem[];
};

// Pousse l'événement purchase dans le dataLayer GA4 (lu par GTM).
export function trackPurchase(order: Purchase) {
  window.dataLayer = window.dataLayer ?? [];
  window.dataLayer.push({ ecommerce: null });
  window.dataLayer.push({
    event: "purchase",
    ecommerce: {
      transaction_id: order.transactionId,
      value: order.value,
      currency: order.currency,
      items: order.items.map((item) => ({
        item_id: item.id,
        item_name: item.name,
        price: item.price,
        quantity: item.quantity,
      })),
    },
  });
}
`;

const NEXT_LEAD = `// components/lead-form.tsx
"use client";

import { useState } from "react";

export function LeadForm() {
  const [done, setDone] = useState(false);

  async function onSubmit(formData: FormData) {
    const res = await fetch("/api/lead", { method: "POST", body: formData });
    if (!res.ok) return;

    window.dataLayer = window.dataLayer ?? [];
    window.dataLayer.push({
      event: "generate_lead",
      form_id: "contact",
      form_destination: "sales",
    });
    setDone(true);
  }

  return (
    <form action={onSubmit}>
      {/* ... champs ... */}
      <button type="submit" disabled={done}>
        Envoyer
      </button>
    </form>
  );
}
`;

const NEXT_CUSTOM = `// lib/analytics.ts
type DataLayerEvent = { event: string } & Record<string, unknown>;

// Événement générique : nommez-le en snake_case, comme GA4.
export function trackEvent(payload: DataLayerEvent) {
  window.dataLayer = window.dataLayer ?? [];
  window.dataLayer.push(payload);
}

// Exemple d'appel, depuis un composant client :
trackEvent({
  event: "demo_requested",
  plan: "pro",
  source: "pricing_header",
});
`;

const WP_PURCHASE = `<?php
// functions.php — événement purchase sur la page de confirmation WooCommerce

add_action( 'woocommerce_thankyou', function ( $order_id ) {
    $order = wc_get_order( $order_id );
    if ( ! $order || $order->get_meta( '_gtm_purchase_pushed' ) ) {
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

    $payload = array(
        'event'     => 'purchase',
        'ecommerce' => array(
            'transaction_id' => $order->get_order_number(),
            'value'          => (float) $order->get_total(),
            'currency'       => $order->get_currency(),
            'items'          => $items,
        ),
    );
    ?>
    <script>
        window.dataLayer = window.dataLayer || [];
        window.dataLayer.push({ ecommerce: null });
        window.dataLayer.push(<?php echo wp_json_encode( $payload ); ?>);
    </script>
    <?php
    $order->update_meta_data( '_gtm_purchase_pushed', 1 );
    $order->save();
}, 20 );
`;

const WP_LEAD = `<?php
// functions.php — événement generate_lead après un envoi Contact Form 7 réussi

add_action( 'wp_footer', function () {
    if ( ! function_exists( 'wpcf7_contact_form' ) ) {
        return;
    }
    ?>
    <script>
        document.addEventListener(
            'wpcf7mailsent',
            function ( event ) {
                window.dataLayer = window.dataLayer || [];
                window.dataLayer.push({
                    event: 'generate_lead',
                    form_id: 'cf7-' + event.detail.contactFormId,
                });
            },
            false
        );
    </script>
    <?php
} );
`;

const WP_CUSTOM = `<?php
// functions.php — événement personnalisé via attribut data-track-event

add_action( 'wp_footer', function () {
    ?>
    <script>
        document.querySelectorAll( '[data-track-event]' ).forEach( function ( el ) {
            el.addEventListener( 'click', function () {
                window.dataLayer = window.dataLayer || [];
                window.dataLayer.push({
                    event: el.dataset.trackEvent,
                    label: el.dataset.trackLabel || null,
                });
            } );
        } );
    </script>
    <?php
} );
`;

const VANILLA_PURCHASE = `// assets/analytics.js — chargé sur la page de confirmation de commande

(function () {
  // La variable order est injectée par le back-end dans le HTML de la page.
  var order = window.__ORDER__;
  if (!order) return;

  window.dataLayer = window.dataLayer || [];
  window.dataLayer.push({ ecommerce: null });
  window.dataLayer.push({
    event: "purchase",
    ecommerce: {
      transaction_id: order.reference,
      value: order.total,
      currency: order.currency,
      items: order.lines.map(function (line) {
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
`;

const VANILLA_LEAD = `// assets/analytics.js

var form = document.querySelector("#lead-form");

if (form) {
  form.addEventListener("submit", function () {
    window.dataLayer = window.dataLayer || [];
    window.dataLayer.push({
      event: "generate_lead",
      form_id: "lead-form",
    });
  });
}
`;

const VANILLA_CUSTOM = `// assets/analytics.js

function trackEvent(name, params) {
  window.dataLayer = window.dataLayer || [];
  window.dataLayer.push(Object.assign({ event: name }, params || {}));
}

// Exemple : clic sur un CTA
var cta = document.querySelector("[data-cta='demo']");
if (cta) {
  cta.addEventListener("click", function () {
    trackEvent("cta_click", { cta_location: "hero" });
  });
}
`;

export const SNIPPETS: Snippet[] = [
  {
    stack: "nextjs",
    event: "purchase",
    lang: "ts",
    filename: "lib/analytics.ts",
    code: NEXT_PURCHASE,
    location: "lib/analytics.ts",
    locationNote:
      "Appelez trackPurchase() dans un effet client sur app/checkout/success/page.tsx, une seule fois, après confirmation du paiement côté serveur.",
  },
  {
    stack: "nextjs",
    event: "lead",
    lang: "tsx",
    filename: "components/lead-form.tsx",
    code: NEXT_LEAD,
    location: "components/lead-form.tsx",
    locationNote:
      "Le push suit la réponse OK de l'API, pas le clic — sinon les envois en échec sont comptés comme des leads.",
  },
  {
    stack: "nextjs",
    event: "custom",
    lang: "ts",
    filename: "lib/analytics.ts",
    code: NEXT_CUSTOM,
    location: "lib/analytics.ts",
    locationNote:
      "Déclarez Window.dataLayer une seule fois dans ce fichier, puis importez trackEvent partout où c'est nécessaire.",
  },
  {
    stack: "wordpress",
    event: "purchase",
    lang: "php",
    filename: "functions.php",
    code: WP_PURCHASE,
    location: "wp-content/themes/<votre-thème>/functions.php",
    locationNote:
      "Ou via l'extension Code Snippets, sans toucher au thème. Le garde-fou _gtm_purchase_pushed évite le double comptage au rechargement de la page.",
  },
  {
    stack: "wordpress",
    event: "lead",
    lang: "php",
    filename: "functions.php",
    code: WP_LEAD,
    location: "wp-content/themes/<votre-thème>/functions.php",
    locationNote:
      "L'événement wpcf7mailsent n'est émis qu'après l'envoi effectif de l'e-mail. Pour Gravity Forms, écoutez plutôt gform_confirmation_loaded.",
  },
  {
    stack: "wordpress",
    event: "custom",
    lang: "php",
    filename: "functions.php",
    code: WP_CUSTOM,
    location: "wp-content/themes/<votre-thème>/functions.php",
    locationNote:
      "Ajoutez l'attribut data-track-event (ex. newsletter_signup) sur les éléments à suivre. Un seul écouteur délégué couvre toute la page.",
  },
  {
    stack: "vanilla",
    event: "purchase",
    lang: "js",
    filename: "assets/analytics.js",
    code: VANILLA_PURCHASE,
    location: "assets/analytics.js",
    locationNote:
      "À charger après le conteneur GTM, uniquement sur l'URL de confirmation (ex. /commande/merci).",
  },
  {
    stack: "vanilla",
    event: "lead",
    lang: "js",
    filename: "assets/analytics.js",
    code: VANILLA_LEAD,
    location: "assets/analytics.js",
    locationNote:
      "Si l'envoi est asynchrone (fetch / XHR), déplacez le push dans le callback de succès pour ne pas compter les erreurs.",
  },
  {
    stack: "vanilla",
    event: "custom",
    lang: "js",
    filename: "assets/analytics.js",
    code: VANILLA_CUSTOM,
    location: "assets/analytics.js",
    locationNote:
      "Exposez trackEvent sur window si d'autres scripts de la page doivent l'appeler.",
  },
];

export function snippetFor(stack: GtmStackId, event: GtmEventId): Snippet {
  return (
    SNIPPETS.find((s) => s.stack === stack && s.event === event) ?? SNIPPETS[0]
  );
}
