import type { Workspace } from "./types";

/**
 * Stand-in for `GET /api/workspaces/:id/audit`. Deterministic per workspace
 * and consistent with /overview and /backlog — the anomalies flagged there
 * show up here as failing event params, exclusion reasons and CWV values.
 */

export type AuditPeriod = "7d" | "30d" | "90d";

export const AUDIT_PERIODS: { id: AuditPeriod; label: string }[] = [
  { id: "7d", label: "7 j" },
  { id: "30d", label: "30 j" },
  { id: "90d", label: "90 j" },
];

const PERIOD_FACTOR: Record<AuditPeriod, number> = {
  "7d": 1,
  "30d": 4.3,
  "90d": 13,
};

export function periodLabel(period: AuditPeriod): string {
  return AUDIT_PERIODS.find((entry) => entry.id === period)?.label ?? "7 j";
}

/* -------------------------------------------------------------------------- */
/*  Block 1 — GA4 observability                                              */
/* -------------------------------------------------------------------------- */

export type EventConformity = "conforme" | "partial" | "missing";

export interface Ga4Event {
  name: string;
  conformity: EventConformity;
  /** Base volume over 7 days; scaled to the selected period by `getAudit`. */
  volume: number;
  /** Verdict shown in the "Validation" column. */
  note: string;
}

export interface Ga4Stream {
  status: "active" | "degraded" | "down";
  /** Badge line, e.g. "Flux actif · 0 perte de paquets". */
  statusLine: string;
  property: string;
  events: Ga4Event[];
}

/* -------------------------------------------------------------------------- */
/*  Block 2 — Search Console index health                                    */
/* -------------------------------------------------------------------------- */

export interface IndexReason {
  label: string;
  urls: number;
}

export interface IndexHealth {
  property: string;
  valid: number;
  excluded: number;
  reasons: IndexReason[];
}

/* -------------------------------------------------------------------------- */
/*  Block 3 — Core Web Vitals                                                */
/* -------------------------------------------------------------------------- */

export type WebVitalId = "lcp" | "inp" | "cls";
export type VitalRating = "good" | "warn" | "bad";

/** Where the measure comes from: CrUX field data or a synthetic lab audit. */
export type VitalSource = "field" | "lab";

export const VITAL_SOURCE_LABEL: Record<VitalSource, string> = {
  field: "Données de terrain (CrUX)",
  lab: "Audit laboratoire (Lighthouse)",
};

/** A costly third-party actor blocking the main thread (INP). */
export interface CostlyEntity {
  name: string;
  /** Human category, e.g. "Tag manager", "Session replay". */
  category: string;
  /** Time the entity kept the main thread busy, in ms. */
  mainThreadMs: number;
  /** Portion of that time that actually blocked input, in ms. */
  blockingMs: number;
}

export interface InpDiagnostic {
  kind: "inp";
  source: VitalSource;
  /** Total Blocking Time over the trace, in ms. */
  totalBlockingTimeMs: number;
  /** Total JS execution time (Lighthouse `bootup-time`), in ms. */
  jsExecutionMs: number;
  entities: CostlyEntity[];
  recommendations: string[];
}

/** An unoptimised asset weighing on the LCP. */
export interface LcpAsset {
  /** Short file name, e.g. "hero-banner.jpg". */
  name: string;
  /** Current encoding, e.g. "JPEG", "PNG". */
  currentFormat: string;
  sizeKb: number;
  /** Estimated saving after AVIF/WebP conversion, in KB. */
  estimatedSavingKb: number;
}

export interface LcpDiagnostic {
  kind: "lcp";
  source: VitalSource;
  /** DOM snippet of the LCP element, e.g. `<img class="hero-image" …>`. */
  elementSnippet: string;
  assets: LcpAsset[];
  /** Ready-to-paste `<link rel="preload">` line. */
  preloadHint: string;
  recommendations: string[];
}

/** A DOM node responsible for a visible layout shift (CLS). */
export interface ClsShiftElement {
  selector: string;
  /** Contribution to the CLS score (0–1). */
  impact: number;
  note: string;
}

export interface ClsDiagnostic {
  kind: "cls";
  source: VitalSource;
  elements: ClsShiftElement[];
  recommendations: string[];
}

export type VitalDiagnostic = InpDiagnostic | LcpDiagnostic | ClsDiagnostic;

export interface WebVital {
  id: WebVitalId;
  label: string;
  /** Rendered value, e.g. "3,4 s". */
  value: string;
  /** Numeric value in the base unit (ms for LCP/INP, unitless for CLS). */
  raw: number;
  rating: VitalRating;
  /** Display target, e.g. "< 2,5 s". */
  target: string;
  /** [good ceiling, needs-improvement ceiling] in the base unit. */
  thresholds: [number, number];
  hint: string;
  /** Surgical diagnostic shown in the inspection drawer. */
  diagnostic?: VitalDiagnostic;
}

export interface AuditData {
  ga4: Ga4Stream;
  index: IndexHealth;
  vitals: WebVital[];
}

const FIXTURES: Record<string, AuditData> = {
  ws_boutique_verte: {
    ga4: {
      status: "active",
      statusLine: "Flux actif · 0 perte de paquets",
      property: "properties/447213908",
      events: [
        { name: "page_view", conformity: "conforme", volume: 48200, note: "100 % conforme" },
        { name: "session_start", conformity: "conforme", volume: 21400, note: "100 % conforme" },
        { name: "view_item", conformity: "conforme", volume: 15900, note: "100 % conforme" },
        { name: "add_to_cart", conformity: "conforme", volume: 3120, note: "100 % conforme" },
        {
          name: "purchase",
          conformity: "missing",
          volume: 412,
          note: "Paramètres manquants : value, currency",
        },
        {
          name: "generate_lead",
          conformity: "partial",
          volume: 86,
          note: "Paramètre recommandé absent : form_id",
        },
      ],
    },
    index: {
      property: "sc-domain:boutique-verte.fr",
      valid: 214,
      excluded: 37,
      reasons: [
        { label: "Exclue par la balise « noindex »", urls: 12 },
        { label: "Page avec redirection", urls: 9 },
        { label: "Explorée, actuellement non indexée", urls: 8 },
        { label: "Introuvable (404)", urls: 5 },
        { label: "Autre page avec balise canonique correcte", urls: 3 },
      ],
    },
    vitals: [
      {
        id: "lcp",
        label: "Largest Contentful Paint",
        value: "3,4 s",
        raw: 3400,
        rating: "warn",
        target: "< 2,5 s",
        thresholds: [2500, 4000],
        hint: "Visuel d'accueil mobile de 1,8 Mo, non préchargé",
      },
      {
        id: "inp",
        label: "Interaction to Next Paint",
        value: "184 ms",
        raw: 184,
        rating: "good",
        target: "< 200 ms",
        thresholds: [200, 500],
        hint: "Interactions fluides sur l'ensemble du tunnel",
      },
      {
        id: "cls",
        label: "Cumulative Layout Shift",
        value: "0,08",
        raw: 0.08,
        rating: "good",
        target: "< 0,1",
        thresholds: [0.1, 0.25],
        hint: "Mise en page stable au chargement",
      },
    ],
  },

  ws_atelier_nord: {
    ga4: {
      status: "active",
      statusLine: "Flux actif · 0 perte de paquets",
      property: "properties/512006644",
      events: [
        { name: "page_view", conformity: "conforme", volume: 12600, note: "100 % conforme" },
        { name: "session_start", conformity: "conforme", volume: 6800, note: "100 % conforme" },
        { name: "view_item", conformity: "conforme", volume: 4100, note: "100 % conforme" },
        { name: "purchase", conformity: "conforme", volume: 220, note: "100 % conforme" },
        {
          name: "generate_lead",
          conformity: "missing",
          volume: 0,
          note: "Événement jamais reçu — formulaires non instrumentés",
        },
      ],
    },
    index: {
      property: "sc-domain:atelier-nord.com",
      valid: 88,
      excluded: 19,
      reasons: [
        { label: "Explorée, actuellement non indexée", urls: 9 },
        { label: "Bloquée par robots.txt", urls: 4 },
        { label: "Introuvable (404)", urls: 3 },
        { label: "Exclue par la balise « noindex »", urls: 3 },
      ],
    },
    vitals: [
      {
        id: "lcp",
        label: "Largest Contentful Paint",
        value: "2,1 s",
        raw: 2100,
        rating: "good",
        target: "< 2,5 s",
        thresholds: [2500, 4000],
        hint: "Hébergement mutualisé, cache de page actif",
      },
      {
        id: "inp",
        label: "Interaction to Next Paint",
        value: "212 ms",
        raw: 212,
        rating: "warn",
        target: "< 200 ms",
        thresholds: [200, 500],
        hint: "Léger blocage sur les filtres produit",
      },
      {
        id: "cls",
        label: "Cumulative Layout Shift",
        value: "0,18",
        raw: 0.18,
        rating: "warn",
        target: "< 0,1",
        thresholds: [0.1, 0.25],
        hint: "Bannière de consentement sans réserve d'espace",
      },
    ],
  },

  ws_studio_lumen: {
    ga4: {
      status: "active",
      statusLine: "Flux actif · 0 perte de paquets",
      property: "properties/399820015",
      events: [
        {
          name: "page_view",
          conformity: "partial",
          volume: 32100,
          note: "≈ 10 % des vues non captées (3 routes lazy)",
        },
        { name: "session_start", conformity: "conforme", volume: 14200, note: "100 % conforme" },
        { name: "view_item", conformity: "conforme", volume: 5600, note: "100 % conforme" },
        { name: "sign_up", conformity: "conforme", volume: 190, note: "100 % conforme" },
        {
          name: "demo_requested",
          conformity: "missing",
          volume: 0,
          note: "Événement jamais reçu — CTA « Demander une démo » non instrumenté",
        },
      ],
    },
    index: {
      property: "sc-domain:studiolumen.io",
      valid: 142,
      excluded: 7,
      reasons: [
        { label: "Explorée, actuellement non indexée", urls: 4 },
        { label: "Page en double sans balise canonique", urls: 2 },
        { label: "Introuvable (404)", urls: 1 },
      ],
    },
    vitals: [
      {
        id: "lcp",
        label: "Largest Contentful Paint",
        value: "1,9 s",
        raw: 1900,
        rating: "good",
        target: "< 2,5 s",
        thresholds: [2500, 4000],
        hint: "Rendu côté serveur, images en AVIF",
      },
      {
        id: "inp",
        label: "Interaction to Next Paint",
        value: "260 ms",
        raw: 260,
        rating: "warn",
        target: "< 200 ms",
        thresholds: [200, 500],
        hint: "Hydratation lourde du tableau de prix sur /tarifs",
      },
      {
        id: "cls",
        label: "Cumulative Layout Shift",
        value: "0,04",
        raw: 0.04,
        rating: "good",
        target: "< 0,1",
        thresholds: [0.1, 0.25],
        hint: "Aucun décalage mesuré",
      },
    ],
  },

  ws_cap_horizon: {
    ga4: {
      status: "active",
      statusLine: "Flux actif · 0 perte de paquets",
      property: "properties/462119003",
      events: [
        { name: "page_view", conformity: "conforme", volume: 27800, note: "100 % conforme" },
        { name: "session_start", conformity: "conforme", volume: 12900, note: "100 % conforme" },
        {
          name: "login",
          conformity: "missing",
          volume: 1240,
          note: "Paramètre manquant : user_id",
        },
        { name: "view_item", conformity: "conforme", volume: 8300, note: "100 % conforme" },
        { name: "purchase", conformity: "conforme", volume: 540, note: "100 % conforme" },
      ],
    },
    index: {
      property: "sc-domain:cap-horizon.co",
      valid: 168,
      excluded: 32,
      reasons: [
        { label: "Explorée, actuellement non indexée", urls: 18 },
        { label: "Exclue par la balise « noindex »", urls: 6 },
        { label: "Page avec redirection", urls: 5 },
        { label: "Introuvable (404)", urls: 3 },
      ],
    },
    vitals: [
      {
        id: "lcp",
        label: "Largest Contentful Paint",
        value: "4,1 s",
        raw: 4100,
        rating: "bad",
        target: "< 2,5 s",
        thresholds: [2500, 4000],
        hint: "Bundle initial de 1,9 Mo, routes non découpées",
      },
      {
        id: "inp",
        label: "Interaction to Next Paint",
        value: "240 ms",
        raw: 240,
        rating: "warn",
        target: "< 200 ms",
        thresholds: [200, 500],
        hint: "Blocage du thread principal au montage des vues",
      },
      {
        id: "cls",
        label: "Cumulative Layout Shift",
        value: "0,06",
        raw: 0.06,
        rating: "good",
        target: "< 0,1",
        thresholds: [0.1, 0.25],
        hint: "Mise en page stable",
      },
    ],
  },
};

/* -------------------------------------------------------------------------- */
/*  Surgical CWV diagnostics — keyed by `${workspaceId}:${vitalId}`           */
/*  Mirrors what the backend PageSpeed probe extracts (P2): costly third      */
/*  parties for INP, unoptimised assets + LCP node for LCP, shifting nodes    */
/*  for CLS. Values stay coherent with each workspace's `hint`.               */
/* -------------------------------------------------------------------------- */

const DIAGNOSTICS: Record<string, VitalDiagnostic> = {
  "ws_boutique_verte:lcp": {
    kind: "lcp",
    source: "field",
    elementSnippet: '<img class="hero-image" src="/img/hero-banner.jpg">',
    assets: [
      {
        name: "hero-banner.jpg",
        currentFormat: "JPEG",
        sizeKb: 1801,
        estimatedSavingKb: 1367,
      },
      {
        name: "collection-2026-large.png",
        currentFormat: "PNG",
        sizeKb: 898,
        estimatedSavingKb: 586,
      },
    ],
    preloadHint:
      '<link rel="preload" as="image" href="/img/hero-banner.avif" fetchpriority="high">',
    recommendations: [
      "Servir le visuel d'accueil en AVIF (repli WebP) — gain estimé ≈ 1,3 Mo.",
      "Précharger l'image LCP dans le <head> avec fetchpriority=\"high\".",
      "Dimensionner le visuel à la taille d'affichage mobile réelle (≤ 720 px de large).",
    ],
  },
  "ws_boutique_verte:inp": {
    kind: "inp",
    source: "field",
    totalBlockingTimeMs: 640,
    jsExecutionMs: 2100,
    entities: [
      {
        name: "Google Tag Manager",
        category: "Tag manager",
        mainThreadMs: 480,
        blockingMs: 210,
      },
      {
        name: "Hotjar",
        category: "Enregistrement de session",
        mainThreadMs: 260,
        blockingMs: 140,
      },
    ],
    recommendations: [
      "Différer le chargement de GTM après le premier rendu (événement `requestIdleCallback` ou interaction).",
      "Charger Hotjar en différé ou le limiter à un échantillon de sessions.",
      "Regrouper les balises tierces derrière un gestionnaire de consentement pour éviter l'exécution au chargement.",
    ],
  },
  "ws_boutique_verte:cls": {
    kind: "cls",
    source: "field",
    elements: [
      {
        selector: "section.hero > img.hero-image",
        impact: 0.05,
        note: "Visuel d'accueil sans width/height — réserve l'espace après chargement.",
      },
      {
        selector: "div.promo-bar",
        impact: 0.03,
        note: "Bandeau promo injecté après l'hydratation, pousse le contenu.",
      },
    ],
    recommendations: [
      "Fixer `width` et `height` (ou `aspect-ratio`) sur le visuel d'accueil.",
      "Réserver la hauteur du bandeau promo via un conteneur à hauteur fixe rendu côté serveur.",
    ],
  },

  "ws_atelier_nord:inp": {
    kind: "inp",
    source: "field",
    totalBlockingTimeMs: 410,
    jsExecutionMs: 1450,
    entities: [
      {
        name: "Filtres produit (bundle interne)",
        category: "Script applicatif",
        mainThreadMs: 320,
        blockingMs: 180,
      },
      {
        name: "Google Tag Manager",
        category: "Tag manager",
        mainThreadMs: 190,
        blockingMs: 90,
      },
    ],
    recommendations: [
      "Découper le script de filtrage et l'exécuter sur interaction plutôt qu'au chargement.",
      "Déplacer le calcul de facettes dans un web worker.",
      "Différer GTM après le premier rendu.",
    ],
  },
  "ws_atelier_nord:cls": {
    kind: "cls",
    source: "field",
    elements: [
      {
        selector: "div.consent-banner",
        impact: 0.12,
        note: "Bannière de consentement sans réserve d'espace, insérée en haut de page.",
      },
      {
        selector: "img.product-thumb",
        impact: 0.04,
        note: "Vignettes produit sans dimensions explicites.",
      },
    ],
    recommendations: [
      "Rendre la bannière de consentement en overlay `position: fixed` (hors flux).",
      "Ajouter `width`/`height` sur toutes les vignettes de la grille produit.",
    ],
  },
  "ws_atelier_nord:lcp": {
    kind: "lcp",
    source: "lab",
    elementSnippet: '<h1 class="page-title">Atelier Nord — mobilier sur mesure</h1>',
    assets: [
      {
        name: "banner-workshop.jpg",
        currentFormat: "JPEG",
        sizeKb: 540,
        estimatedSavingKb: 360,
      },
    ],
    preloadHint:
      '<link rel="preload" as="font" href="/fonts/canela.woff2" type="font/woff2" crossorigin>',
    recommendations: [
      "Précharger la police du titre pour éviter le rendu différé du texte LCP.",
      "Compresser la bannière d'atelier et la servir en WebP.",
    ],
  },

  "ws_studio_lumen:inp": {
    kind: "inp",
    source: "field",
    totalBlockingTimeMs: 520,
    jsExecutionMs: 1980,
    entities: [
      {
        name: "Table de prix (hydratation React)",
        category: "Script applicatif",
        mainThreadMs: 610,
        blockingMs: 280,
      },
      {
        name: "Intercom",
        category: "Chat support",
        mainThreadMs: 240,
        blockingMs: 110,
      },
    ],
    recommendations: [
      "Rendre la table de prix côté serveur et n'hydrater que les contrôles interactifs.",
      "Charger Intercom après interaction (clic sur la bulle) plutôt qu'au chargement.",
    ],
  },
  "ws_studio_lumen:lcp": {
    kind: "lcp",
    source: "field",
    elementSnippet: '<img class="case-study-cover" src="/media/lumen-cover.avif">',
    assets: [],
    preloadHint:
      '<link rel="preload" as="image" href="/media/lumen-cover.avif" fetchpriority="high">',
    recommendations: [
      "Le visuel LCP est déjà en AVIF — ajouter un `preload` pour le prioriser.",
      "Réduire la chaîne de requêtes critiques (police + CSS) qui retarde l'affichage.",
    ],
  },
  "ws_studio_lumen:cls": {
    kind: "cls",
    source: "field",
    elements: [
      {
        selector: "table.pricing-grid",
        impact: 0.03,
        note: "La table de prix se redimensionne à l'hydratation sur /tarifs.",
      },
    ],
    recommendations: [
      "Fixer la hauteur minimale de la table de prix pendant l'hydratation.",
    ],
  },

  "ws_cap_horizon:lcp": {
    kind: "lcp",
    source: "lab",
    elementSnippet: '<div class="hero-carousel" data-slide="1"></div>',
    assets: [
      {
        name: "app-main.js",
        currentFormat: "JS",
        sizeKb: 1904,
        estimatedSavingKb: 0,
      },
      {
        name: "slide-01.jpg",
        currentFormat: "JPEG",
        sizeKb: 720,
        estimatedSavingKb: 470,
      },
    ],
    preloadHint:
      '<link rel="preload" as="image" href="/img/slide-01.webp" fetchpriority="high">',
    recommendations: [
      "Découper le bundle initial (1,9 Mo) par route — le carrousel n'a pas besoin de tout l'applicatif.",
      "Servir la première diapositive en WebP et la précharger.",
      "Retarder l'initialisation JS du carrousel jusqu'à la visibilité (`IntersectionObserver`).",
    ],
  },
  "ws_cap_horizon:inp": {
    kind: "inp",
    source: "field",
    totalBlockingTimeMs: 700,
    jsExecutionMs: 2450,
    entities: [
      {
        name: "Bundle applicatif (montage des vues)",
        category: "Script applicatif",
        mainThreadMs: 890,
        blockingMs: 360,
      },
      {
        name: "Google Tag Manager",
        category: "Tag manager",
        mainThreadMs: 210,
        blockingMs: 95,
      },
    ],
    recommendations: [
      "Activer le fractionnement de code par route pour alléger le montage initial.",
      "Différer GTM et les scripts non critiques après `load`.",
      "Mesurer les longues tâches (> 50 ms) et les découper.",
    ],
  },
  "ws_cap_horizon:cls": {
    kind: "cls",
    source: "field",
    elements: [
      {
        selector: "div.hero-carousel",
        impact: 0.04,
        note: "Le carrousel n'a pas de hauteur réservée avant initialisation JS.",
      },
    ],
    recommendations: [
      "Réserver la hauteur du carrousel via `aspect-ratio` ou une hauteur fixe en CSS.",
    ],
  },
};

export function getAudit(workspace: Workspace, period: AuditPeriod): AuditData {
  const key = FIXTURES[workspace.id] ? workspace.id : "ws_boutique_verte";
  const base = FIXTURES[key];
  const factor = PERIOD_FACTOR[period];

  return {
    ...base,
    ga4: {
      ...base.ga4,
      events: base.ga4.events.map((event) => ({
        ...event,
        volume: Math.round(event.volume * factor),
      })),
    },
    vitals: base.vitals.map((vital) => {
      const diagnostic = DIAGNOSTICS[`${key}:${vital.id}`];
      return diagnostic ? { ...vital, diagnostic } : vital;
    }),
  };
}
