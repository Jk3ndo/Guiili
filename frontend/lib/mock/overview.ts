import type {
  AuditEvent,
  MetricScore,
  OverviewData,
  PriorityRecommendation,
  Workspace,
} from "./types";

/**
 * Stand-in for `GET /api/workspaces/:id/overview`. Deterministic per workspace
 * so switching sites in the sidebar visibly changes the numbers.
 */

interface Fixture {
  lastScanHoursAgo: number;
  metrics: MetricScore[];
  recommendation: PriorityRecommendation | null;
  events: Omit<AuditEvent, "id" | "hoursAgo">[];
  /** Hours ago, parallel to `events`. */
  eventTimes: number[];
}

const FIXTURES: Record<string, Fixture> = {
  ws_boutique_verte: {
    lastScanHoursAgo: 2,
    metrics: [
      {
        id: "ga4",
        label: "Santé GA4",
        value: "92",
        status: "good",
        delta: 3,
        verdict: "Événements clés suivis",
        hint: "Flux temps réel actif",
      },
      {
        id: "gsc",
        label: "Indexation GSC",
        value: "78 %",
        status: "warn",
        delta: -1,
        verdict: "12 pages produit hors index",
        hint: "Sitemap à resoumettre",
      },
      {
        id: "cwv",
        label: "Core Web Vitals",
        value: "61",
        status: "bad",
        delta: 6,
        verdict: "LCP 3,4 s sur mobile",
        hint: "Images hero non optimisées",
      },
    ],
    recommendation: {
      severity: "high",
      title: "Le tag GA4 e-commerce ne remonte pas la valeur des transactions",
      detail:
        "L'événement purchase est bien envoyé mais sans paramètre value ni items. Les revenus GA4 sont donc nuls alors que les ventes ont lieu.",
      impact: "≈ 38 % des conversions sans revenu attribué",
      cta: { label: "Générer le conteneur GTM", kind: "gtm" },
    },
    events: [
      {
        kind: "scan",
        action: "Diagnostic complet exécuté",
        target: "boutique-verte.fr",
        result: "success",
      },
      {
        kind: "export",
        action: "Conteneur GTM exporté",
        target: "GTM-PK2X9QM",
        result: "success",
      },
      {
        kind: "snippet",
        action: "Snippet dataLayer généré",
        target: "/checkout/success",
        result: "success",
      },
      {
        kind: "connection",
        action: "Propriété GA4 reliée",
        target: "properties/447213908",
        result: "success",
      },
    ],
    eventTimes: [2, 27, 74, 121],
  },
  ws_atelier_nord: {
    lastScanHoursAgo: 148,
    metrics: [
      {
        id: "ga4",
        label: "Santé GA4",
        value: "64",
        status: "warn",
        delta: -4,
        verdict: "Formulaires non instrumentés",
        hint: "≈ 60 leads / mois non tracés",
      },
      {
        id: "gsc",
        label: "Indexation GSC",
        value: "—",
        status: "bad",
        delta: 0,
        verdict: "Reconnexion GSC requise",
        hint: "Aucune donnée d'indexation depuis 6 jours",
      },
      {
        id: "cwv",
        label: "Core Web Vitals",
        value: "73",
        status: "warn",
        delta: 2,
        verdict: "CLS 0,18 en page d'accueil",
        hint: "Bannière cookie sans réserve d'espace",
      },
    ],
    recommendation: {
      severity: "high",
      title: "La connexion Search Console a expiré",
      detail:
        "Aucune donnée d'indexation ni de position depuis 6 jours. Le diagnostic tourne en aveugle sur la partie SEO.",
      impact: "6 jours de données SEO manquantes",
      cta: { label: "Voir le snippet de reconnexion", kind: "snippet" },
    },
    events: [
      {
        kind: "connection",
        action: "Échec de rafraîchissement du token GSC",
        target: "sc-domain:atelier-nord.com",
        result: "error",
      },
      {
        kind: "scan",
        action: "Diagnostic partiel exécuté",
        target: "atelier-nord.com",
        result: "success",
      },
      {
        kind: "snippet",
        action: "Snippet WooCommerce généré",
        target: "hook woocommerce_thankyou",
        result: "success",
      },
      {
        kind: "export",
        action: "Conteneur GTM exporté",
        target: "GTM-T7R4WZ2",
        result: "success",
      },
    ],
    eventTimes: [140, 148, 220, 400],
  },
  ws_studio_lumen: {
    lastScanHoursAgo: 9,
    metrics: [
      {
        id: "ga4",
        label: "Santé GA4",
        value: "88",
        status: "good",
        delta: 1,
        verdict: "Suivi SPA opérationnel",
        hint: "Pages vues captées via History Change",
      },
      {
        id: "gsc",
        label: "Indexation GSC",
        value: "95 %",
        status: "good",
        delta: 2,
        verdict: "95 % des pages indexées",
        hint: "3 pages en cours d'exploration",
      },
      {
        id: "cwv",
        label: "Core Web Vitals",
        value: "79",
        status: "warn",
        delta: -3,
        verdict: "INP 260 ms sur /tarifs",
        hint: "Hydratation lourde du tableau de prix",
      },
    ],
    recommendation: {
      severity: "medium",
      title: "Le clic sur « Demander une démo » n'est pas suivi",
      detail:
        "Le CTA principal ouvre une modale sans push dataLayer. Impossible de mesurer le taux de clic vers la démo depuis GA4.",
      impact: "Principal objectif de conversion non mesuré",
      cta: { label: "Voir le snippet", kind: "snippet" },
    },
    events: [
      {
        kind: "scan",
        action: "Diagnostic complet exécuté",
        target: "studiolumen.io",
        result: "success",
      },
      {
        kind: "snippet",
        action: "Composable Vue analytics généré",
        target: "router afterEach",
        result: "success",
      },
      {
        kind: "export",
        action: "Conteneur GTM exporté",
        target: "GTM-9LMN3KD",
        result: "success",
      },
      {
        kind: "scan",
        action: "Alerte de régression CWV levée",
        target: "studiolumen.io/tarifs",
        result: "success",
      },
    ],
    eventTimes: [9, 30, 52, 96],
  },
  ws_cap_horizon: {
    lastScanHoursAgo: 20,
    metrics: [
      {
        id: "ga4",
        label: "Santé GA4",
        value: "71",
        status: "warn",
        delta: -2,
        verdict: "user_id absent après login",
        hint: "Rapprochement cross-device inactif",
      },
      {
        id: "gsc",
        label: "Indexation GSC",
        value: "84 %",
        status: "good",
        delta: 4,
        verdict: "Indexation en hausse",
        hint: "Sitemap resoumis la semaine passée",
      },
      {
        id: "cwv",
        label: "Core Web Vitals",
        value: "58",
        status: "bad",
        delta: -5,
        verdict: "Bundle initial de 1,9 Mo",
        hint: "Lazy-loading des routes à activer",
      },
    ],
    recommendation: {
      severity: "high",
      title: "L'identifiant utilisateur n'est pas transmis à GA4",
      detail:
        "Après connexion, aucun set user_id n'est poussé. Le rapprochement cross-device et les audiences connectées sont donc inopérants.",
      impact: "≈ 45 % de sessions dupliquées entre appareils",
      cta: { label: "Générer le conteneur GTM", kind: "gtm" },
    },
    events: [
      {
        kind: "scan",
        action: "Diagnostic complet exécuté",
        target: "cap-horizon.co",
        result: "success",
      },
      {
        kind: "snippet",
        action: "AnalyticsService Angular généré",
        target: "AuthService.onLogin",
        result: "success",
      },
      {
        kind: "connection",
        action: "Conteneur GTM relié",
        target: "GTM-CH5PQ8V",
        result: "success",
      },
      {
        kind: "export",
        action: "Conteneur GTM exporté",
        target: "GTM-CH5PQ8V",
        result: "success",
      },
    ],
    eventTimes: [20, 44, 70, 110],
  },
};

export function getOverview(workspace: Workspace): OverviewData {
  const fx = FIXTURES[workspace.id] ?? FIXTURES.ws_boutique_verte;
  return {
    siteName: workspace.name,
    domain: workspace.domain,
    stack: workspace.stack,
    lastScanHoursAgo: fx.lastScanHoursAgo,
    metrics: fx.metrics,
    recommendation: fx.recommendation,
    events: fx.events.map((e, i) => ({
      ...e,
      id: `${workspace.id}_ev${i}`,
      hoursAgo: fx.eventTimes[i],
    })),
  };
}
