import type {
  MeasurementItemDto,
  MeasurementLayer,
  SiteType,
} from "@/lib/api/measurement";

export const LAYER_LABEL: Record<MeasurementLayer, string> = {
  foundations: "Fondations",
  events: "Événements clés",
  conversions: "Conversions",
  ads: "Publicité Google Ads",
  seo: "Base SEO",
};

export const SITE_TYPE_LABEL: Record<SiteType, string> = {
  ecommerce: "Boutique en ligne",
  lead_gen: "Prise de contact / devis",
  saas: "Logiciel (SaaS)",
  content: "Contenu / blog",
  other: "Autre",
};

/**
 * Codes de raison du backend (`MeasurementItemDto.reason`) -> texte français.
 * `connection_needs_reauth` couvre aussi une panne réseau transitoire : « à revérifier »,
 * jamais « révoquée ». `api_error` = « non vérifiable ».
 */
export const REASON_LABEL: Record<string, string> = {
  ga4_not_connected: "Connecte Google (un clic) pour aller plus loin.",
  headless_not_run: "Lance la vérification « en conditions réelles » pour trancher.",
  manual_check: "À vérifier à la main, puis à marquer comme fait.",
  token_unavailable: "À revérifier : la connexion Google est indisponible pour le moment.",
  connection_needs_reauth:
    "À revérifier : la connexion Google doit être renouvelée ou est momentanément indisponible.",
  permission_or_api_disabled: "Droits ou API Google insuffisants pour lire cette donnée.",
  quota: "Quota Google atteint, réessaie plus tard.",
  network: "Réseau indisponible, réessaie.",
  api_error: "Non vérifiable pour le moment (erreur de l'API Google).",
  not_found: "Ressource Google introuvable.",
  fetch_error: "Le site est injoignable.",
  http_error: "Le site a répondu par une erreur.",
  non_html: "La page d'accueil n'est pas une page web.",
  page_unavailable: "Page indisponible.",
  gtm_absent: "GTM n'est pas installé.",
  gtm_not_loaded_in_browser:
    "GTM est dans le code mais ne se charge pas dans un vrai navigateur.",
  purchase_not_received: "Aucun achat reçu par GA4 pour l'instant.",
  position_unknown: "Position du snippet indéterminée.",
  no_tracking_found: "Aucun suivi trouvé sur la page.",
  not_checked: "Pas encore vérifié.",
  gsc_not_connected: "Connecte Google (un clic) pour relier Search Console.",
  robots_unreadable: "Le fichier robots.txt n'a pas pu être lu.",
  cmp_not_detected: "Aucune bannière de consentement (CMP) détectée.",
  consent_default_not_seen: "Aucun consentement par défaut observé dans le navigateur.",
  consent_may_block_tags:
    "Ton site demande un consentement avant d'envoyer les balises : la vérification automatique ne clique pas la bannière, donc elle ne peut pas trancher.",
  cmp_default_not_observed:
    "Une bannière de consentement est détectée, mais son réglage par défaut n'est pas visible depuis l'extérieur.",
  ads_conversion_needs_event:
    "Une balise de conversion ne se déclenche que sur l'action mesurée (achat, formulaire) : on ne peut pas la voir depuis la page d'accueil.",
  tls_unreachable:
    "Le certificat n'a pas pu être contrôlé (site injoignable à ce moment-là). Clique sur « Vérifier maintenant ».",
};

/** Texte d'une raison ; un code inconnu (backend plus récent) n'affiche rien plutôt qu'un code brut. */
export function reasonLabel(reason: string | null): string | null {
  if (reason === null) return null;
  return REASON_LABEL[reason] ?? null;
}

/** Items « reçus » dont la preuve vient de l'API d'administration de GA4, pas de ses données. */
const CONFIRMED_IN_GA4 = new Set(["ads_ga4_link", "key_events_marked", "conversion_value"]);

/** Libellé du niveau « reçu » selon la source réelle de la preuve. */
function receivedLabel(item: MeasurementItemDto): string {
  if (item.layer === "seo") return "Confirmé par Search Console";
  if (CONFIRMED_IN_GA4.has(item.id)) return "Confirmé dans GA4";
  return "Reçu par GA4";
}

export function stateLabel(item: MeasurementItemDto): string {
  if (item.done) return item.max_level === "on_page" ? "En place" : receivedLabel(item);
  switch (item.state) {
    case "received":
      return receivedLabel(item);
    case "on_page":
      return "Présent sur la page";
    case "missing":
      return "Manquant";
    case "unverifiable":
      return "À confirmer";
    case "not_applicable":
      return "Non concerné";
    case "dismissed":
      return "Écarté";
    default:
      return "Pas encore vérifié";
  }
}

/** Classe de la pastille de statut : uniquement des couleurs de statut. */
export function stateDotClass(item: MeasurementItemDto): string {
  if (item.done) return "bg-ok";
  if (item.partial) return "bg-warn";
  if (item.state === "missing") return "bg-danger";
  return "bg-ink-faint";
}
