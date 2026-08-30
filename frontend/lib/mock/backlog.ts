import type { Workspace } from "./types";

/**
 * Stand-in for `GET /api/workspaces/:id/backlog`. Deterministic per workspace
 * and aligned with the issues surfaced on /overview — the priority
 * recommendation there is the first "à traiter" critical item here.
 */

export type IssueCategory = "gtm" | "ga4" | "vitals" | "indexation";
export type IssueSeverity = "critical" | "warning" | "info";
export type IssueStatus = "todo" | "in_progress" | "done";

export type FixLang = "ts" | "tsx" | "js" | "php" | "json" | "css";

export interface IssueFix {
  /** Lead-in shown above the snippet or the steps. */
  summary: string;
  /** Exact file the patch targets, when there is one. */
  file?: string;
  /** A copy-pasteable patch. */
  code?: string;
  lang?: FixLang;
  /** A short correction procedure (used when there is no single snippet). */
  steps?: string[];
}

export interface IssueItem {
  id: string;
  title: string;
  context: string;
  /** Quantified consequence, shown in the detail drawer. */
  impact: string;
  category: IssueCategory;
  severity: IssueSeverity;
  status: IssueStatus;
  detectedDaysAgo: number;
  fix: IssueFix;
}

export const CATEGORY_LABEL: Record<IssueCategory, string> = {
  gtm: "GTM",
  ga4: "GA4",
  vitals: "Web Vitals",
  indexation: "Indexation",
};

export const SEVERITY_LABEL: Record<IssueSeverity, string> = {
  critical: "Critique",
  warning: "Warning",
  info: "Info",
};

export const STATUS_LABEL: Record<IssueStatus, string> = {
  todo: "À traiter",
  in_progress: "En cours",
  done: "Résolu",
};

export const STATUS_ORDER: IssueStatus[] = ["todo", "in_progress", "done"];

const FIXTURES: Record<string, IssueItem[]> = {
  ws_boutique_verte: [
    {
      id: "bv-1",
      title: "L'événement purchase GA4 ne transmet ni value ni items",
      context:
        "Le tag se déclenche à chaque commande mais l'objet ecommerce envoyé est vide.",
      impact: "≈ 38 % des commandes sans revenu dans les rapports GA4",
      category: "ga4",
      severity: "critical",
      status: "todo",
      detectedDaysAgo: 4,
      fix: {
        summary:
          "Ajoutez value, currency et items à l'objet ecommerce avant l'envoi de l'événement purchase.",
        file: "lib/analytics.ts",
        lang: "ts",
        code: `// lib/analytics.ts — appelé sur /checkout/success, paiement confirmé
export function trackPurchase(order: {
  id: string;
  revenue: number;
  currency: string;
  items: { sku: string; name: string; price: number; qty: number }[];
}) {
  window.dataLayer = window.dataLayer ?? [];
  window.dataLayer.push({ ecommerce: null });
  window.dataLayer.push({
    event: "purchase",
    ecommerce: {
      transaction_id: order.id,
      value: order.revenue, // absent aujourd'hui
      currency: order.currency, // absent aujourd'hui
      items: order.items.map((it) => ({
        item_id: it.sku,
        item_name: it.name,
        price: it.price,
        quantity: it.qty,
      })),
    },
  });
}
`,
      },
    },
    {
      id: "bv-2",
      title: "12 pages produit absentes de l'index Google",
      context:
        "Une balise noindex héritée du template de préproduction bloque l'indexation.",
      impact: "12 URLs produit invisibles dans la recherche Google",
      category: "indexation",
      severity: "warning",
      status: "in_progress",
      detectedDaysAgo: 9,
      fix: {
        summary:
          "Le noindex vient d'un template partagé avec l'environnement de préproduction.",
        steps: [
          "Retirer la balise meta robots noindex du template produit.",
          "Vérifier qu'aucune règle Disallow ne bloque /produit/ dans robots.txt.",
          "Régénérer le sitemap et le resoumettre dans Search Console.",
          "Demander l'indexation des 12 URLs prioritaires via l'inspection d'URL.",
        ],
      },
    },
    {
      id: "bv-3",
      title: "LCP à 3,4 s sur mobile — visuel d'accueil non optimisé",
      context:
        "Le visuel hero pèse 1,8 Mo, n'est pas préchargé et n'est pas servi en AVIF.",
      impact: "LCP mobile à 3,4 s — au-dessus du seuil « bon » de 2,5 s",
      category: "vitals",
      severity: "warning",
      status: "todo",
      detectedDaysAgo: 6,
      fix: {
        summary:
          "Servez le visuel via next/image avec priority, et exportez-le en AVIF sous 200 Ko.",
        file: "app/(marketing)/page.tsx",
        lang: "tsx",
        code: `// app/(marketing)/page.tsx
import Image from "next/image";
import hero from "@/public/hero.avif";

export function Hero() {
  return (
    <Image
      src={hero}
      alt="Atelier de la Boutique Verte"
      priority // précharge le LCP
      sizes="100vw"
      placeholder="blur"
      className="h-auto w-full"
    />
  );
}
`,
      },
    },
    {
      id: "bv-4",
      title: "Deux balises GA4 se déclenchaient avant le consentement",
      context:
        "Résolu le 12/08 : le déclenchement est conditionné au consentement analytics_storage.",
      impact: "Résolu — plus aucune collecte GA4 avant consentement",
      category: "gtm",
      severity: "info",
      status: "done",
      detectedDaysAgo: 24,
      fix: {
        summary:
          "Correctif appliqué : les balises GA4 attendent désormais le consentement.",
        steps: [
          "Ajout d'une variable de couche de données analytics_consent.",
          "Déclenchement des balises GA4 conditionné à analytics_consent = granted.",
          "Conteneur republié le 12/08.",
        ],
      },
    },
    {
      id: "bv-5",
      title: "Les paramètres UTM ne sont pas capturés en variable GTM",
      context:
        "Les campagnes payantes ne peuvent pas être attribuées dans les rapports GA4.",
      impact: "Campagnes payantes non attribuables dans GA4",
      category: "gtm",
      severity: "warning",
      status: "todo",
      detectedDaysAgo: 12,
      fix: {
        summary:
          "Créez une variable d'URL par paramètre UTM, puis mappez-les en paramètres d'événement GA4.",
        file: "Espace de travail GTM — Variables",
        lang: "json",
        code: `{
  "name": "URL - utm_source",
  "type": "u",
  "parameter": [
    { "type": "template", "key": "component", "value": "QUERY" },
    { "type": "template", "key": "queryKey", "value": "utm_source" }
  ]
}
`,
      },
    },
  ],

  ws_atelier_nord: [
    {
      id: "an-1",
      title: "Connexion Search Console expirée depuis 6 jours",
      context:
        "Aucune donnée d'indexation ni de position : le diagnostic SEO tourne en aveugle.",
      impact: "6 jours de données SEO manquantes et comptant",
      category: "indexation",
      severity: "critical",
      status: "todo",
      detectedDaysAgo: 6,
      fix: {
        summary:
          "Le jeton a expiré (rotation 7 jours). Seule une reconnexion est requise, aucune écriture.",
        steps: [
          "Ouvrir Connexions Google et repérer dev.agence@gmail.com (statut ambre).",
          "Cliquer sur Re-synchroniser pour relancer le consentement OAuth.",
          "Confirmer le périmètre webmasters.readonly.",
          "Relancer un diagnostic complet une fois le jeton renouvelé.",
        ],
      },
    },
    {
      id: "an-2",
      title: "Formulaires WooCommerce non instrumentés (generate_lead)",
      context: "Aucun formulaire ne pousse d'événement dans la couche de données.",
      impact: "≈ 60 leads par mois non tracés dans GA4",
      category: "ga4",
      severity: "warning",
      status: "todo",
      detectedDaysAgo: 15,
      fix: {
        summary:
          "Ce hook couvre tous les Contact Form 7 du site, sans toucher aux templates.",
        file: "wp-content/themes/<thème>/functions.php",
        lang: "php",
        code: `<?php
// functions.php — événement generate_lead après un envoi Contact Form 7

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
`,
      },
    },
    {
      id: "an-3",
      title: "CLS 0,18 en page d'accueil — bannière cookie sans réserve",
      context: "La bannière de consentement s'insère après le rendu et pousse le contenu.",
      impact: "CLS 0,18 — au-dessus du seuil « bon » de 0,1",
      category: "vitals",
      severity: "warning",
      status: "in_progress",
      detectedDaysAgo: 11,
      fix: {
        summary: "Réservez la hauteur de la bannière pour supprimer le décalage.",
        file: "assets/css/cookie-banner.css",
        lang: "css",
        code: `/* Réserve l'espace de la bannière avant son hydratation. */
.cookie-banner {
  min-height: 96px;
  contain: layout;
}

@media (min-width: 768px) {
  .cookie-banner {
    min-height: 64px;
  }
}
`,
      },
    },
    {
      id: "an-4",
      title: "Le conteneur GTM se chargeait deux fois",
      context: "Résolu le 03/08 : snippet présent dans le thème et dans une extension.",
      impact: "Résolu — un seul chargement du conteneur",
      category: "gtm",
      severity: "warning",
      status: "done",
      detectedDaysAgo: 30,
      fix: {
        summary: "Correctif appliqué : le conteneur ne se charge plus qu'une fois.",
        steps: [
          "Snippet GTM présent dans header.php et dans l'extension Site Kit.",
          "Suppression du snippet manuel du thème.",
          "Vérification en mode Aperçu : un seul chargement — fait le 03/08.",
        ],
      },
    },
  ],

  ws_studio_lumen: [
    {
      id: "sl-1",
      title: "Le CTA « Demander une démo » n'émet aucun événement",
      context: "Le bouton ouvre une modale sans push dans la couche de données.",
      impact: "Objectif de conversion principal non mesuré",
      category: "ga4",
      severity: "warning",
      status: "todo",
      detectedDaysAgo: 3,
      fix: {
        summary: "Poussez cta_click au clic sur le bouton, avant l'ouverture de la modale.",
        file: "components/demo-cta.tsx",
        lang: "tsx",
        code: `// components/demo-cta.tsx
"use client";

export function DemoCta() {
  function handleClick() {
    window.dataLayer = window.dataLayer ?? [];
    window.dataLayer.push({
      event: "cta_click",
      cta_label: "Demander une démo",
      cta_location: "hero",
    });
  }

  return (
    <button type="button" onClick={handleClick}>
      Demander une démo
    </button>
  );
}
`,
      },
    },
    {
      id: "sl-2",
      title: "INP 260 ms sur /tarifs — hydratation lourde du tableau de prix",
      context: "Le tableau recalcule toutes ses lignes à chaque bascule mensuel / annuel.",
      impact: "INP 260 ms sur /tarifs — au-dessus du seuil « bon » de 200 ms",
      category: "vitals",
      severity: "warning",
      status: "todo",
      detectedDaysAgo: 8,
      fix: {
        summary: "Isolez le tableau de prix et mémoïsez son calcul.",
        steps: [
          "Profiler /tarifs avec l'onglet Performance (interaction = bascule de période).",
          "Extraire le tableau dans un composant client chargé via next/dynamic.",
          "Mémoïser le calcul des lignes de prix avec useMemo.",
          "Cible : INP sous 200 ms.",
        ],
      },
    },
    {
      id: "sl-3",
      title: "Suivi SPA : 3 routes lazy sans page_view",
      context: "History Change couvre 90 % des vues ; 3 routes chargées en lazy sont muettes.",
      impact: "≈ 10 % des pages vues SPA non comptées",
      category: "ga4",
      severity: "info",
      status: "in_progress",
      detectedDaysAgo: 14,
      fix: {
        summary: "Ce tracker couvre toutes les navigations App Router, y compris les routes lazy.",
        file: "app/providers/page-view-tracker.tsx",
        lang: "tsx",
        code: `// app/providers/page-view-tracker.tsx
"use client";

import { usePathname } from "next/navigation";
import { useEffect } from "react";

export function PageViewTracker() {
  const pathname = usePathname();

  useEffect(() => {
    window.dataLayer = window.dataLayer ?? [];
    window.dataLayer.push({ event: "page_view", page_path: pathname });
  }, [pathname]);

  return null;
}
`,
      },
    },
    {
      id: "sl-4",
      title: "Sitemap non déclaré dans robots.txt",
      context: "Résolu le 09/08 : la ligne Sitemap a été ajoutée et resoumise.",
      impact: "Résolu — sitemap déclaré et resoumis",
      category: "indexation",
      severity: "info",
      status: "done",
      detectedDaysAgo: 20,
      fix: {
        summary: "Correctif appliqué : le sitemap est déclaré dans robots.txt.",
        steps: [
          "Ligne Sitemap absente de robots.txt.",
          "Ajout de Sitemap: https://studiolumen.io/sitemap.xml.",
          "Resoumission dans Search Console — fait le 09/08.",
        ],
      },
    },
  ],

  ws_cap_horizon: [
    {
      id: "ch-1",
      title: "L'identifiant utilisateur n'est pas transmis à GA4",
      context:
        "Aucun user_id après connexion : le rapprochement cross-device est inopérant.",
      impact: "≈ 45 % de sessions dupliquées entre appareils",
      category: "ga4",
      severity: "critical",
      status: "todo",
      detectedDaysAgo: 5,
      fix: {
        summary: "Poussez user_id juste après le login ; GTM le relaie à GA4 via le champ User ID.",
        file: "lib/analytics.ts",
        lang: "ts",
        code: `// lib/analytics.ts — après authentification réussie
export function identifyUser(userId: string) {
  window.dataLayer = window.dataLayer ?? [];
  window.dataLayer.push({
    event: "login",
    user_id: userId, // identifiant stable, jamais l'e-mail en clair
  });
}
`,
      },
    },
    {
      id: "ch-2",
      title: "Bundle initial de 1,9 Mo — routes non découpées",
      context: "Le lazy-loading par route n'est pas activé ; tout part dans le premier bundle.",
      impact: "LCP mobile à 4,1 s, bundle initial de 1,9 Mo",
      category: "vitals",
      severity: "critical",
      status: "todo",
      detectedDaysAgo: 7,
      fix: {
        summary: "Activez le découpage par route et différez les librairies tierces non critiques.",
        steps: [
          "Analyser le bundle avec l'analyseur de Next.",
          "Activer le lazy-loading des modules non critiques par route.",
          "Différer chat, A/B testing et autres scripts tiers.",
          "Cible : bundle initial sous 300 Ko, LCP mobile sous 2,5 s.",
        ],
      },
    },
    {
      id: "ch-3",
      title: "Indexation en progression après resoumission du sitemap",
      context: "84 % des pages indexées, en hausse de 4 points sur la semaine.",
      impact: "Indexation à 84 %, +4 points sur la semaine",
      category: "indexation",
      severity: "info",
      status: "in_progress",
      detectedDaysAgo: 6,
      fix: {
        summary: "Suivi en cours, aucune action bloquante.",
        steps: [
          "Sitemap resoumis le 21/08.",
          "Couverture suivie chaque semaine dans Search Console.",
          "Exploration des nouvelles URLs en cours par Google.",
        ],
      },
    },
    {
      id: "ch-4",
      title: "Le conteneur GTM se chargeait après l'hydratation",
      context: "Résolu le 15/08 : le snippet est désormais dans le <head>.",
      impact: "Résolu — conteneur chargé avant le premier événement",
      category: "gtm",
      severity: "warning",
      status: "done",
      detectedDaysAgo: 18,
      fix: {
        summary: "Correctif appliqué : le conteneur se charge avant le premier événement.",
        steps: [
          "Snippet GTM chargé en fin de body, après l'hydratation React.",
          "Déplacement dans le <head> via next/script strategy=beforeInteractive.",
          "Vérification du chargement prioritaire — fait le 15/08.",
        ],
      },
    },
  ],
};

export function getBacklog(workspace: Workspace): IssueItem[] {
  return FIXTURES[workspace.id] ?? FIXTURES.ws_boutique_verte;
}
