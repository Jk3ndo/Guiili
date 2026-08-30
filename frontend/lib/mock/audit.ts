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

export function getAudit(workspace: Workspace, period: AuditPeriod): AuditData {
  const base = FIXTURES[workspace.id] ?? FIXTURES.ws_boutique_verte;
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
  };
}
