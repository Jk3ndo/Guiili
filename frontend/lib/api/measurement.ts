import { ApiError, apiGet, apiPatch, apiPostSlow } from "./client";

// Types alignés sur les schémas de sortie de
// `backend/app/api/v1/endpoints/measurement.py` (le backend fait foi).

export type MeasurementState =
  | "unknown"
  | "missing"
  | "on_page"
  | "received"
  | "unverifiable"
  | "not_applicable"
  | "dismissed";

export type MeasurementLayer =
  | "foundations"
  | "events"
  | "conversions"
  | "ads"
  | "seo";

export type SiteType = "ecommerce" | "lead_gen" | "saas" | "content" | "other";

export type GoogleConnectionState = "none" | "active" | "needs_reauth";

export interface MeasurementSnippetDto {
  language: string;
  code: string;
  target_path: string;
  instructions: string;
}

export interface MeasurementItemDto {
  id: string;
  layer: MeasurementLayer;
  title: string;
  why: string;
  weight: number;
  quick_win: boolean;
  max_level: "on_page" | "received";
  state: MeasurementState;
  done: boolean;
  partial: boolean;
  /** Code stable décidé par le backend (voir `REASON_LABEL`), jamais du texte libre. */
  reason: string | null;
  evidence: Record<string, unknown>;
  checked_at: string | null;
  guide: string[];
  actions: ("guide" | "snippet" | "gtm_container" | "advisor" | "pr")[];
  snippet: MeasurementSnippetDto | null;
}

export interface TypeGuessDto {
  type: SiteType;
  confidence: number;
  signals: string[];
}

export interface MeasurementProfileDto {
  detected_types: TypeGuessDto[];
  confirmed_types: SiteType[] | null;
  effective_types: SiteType[];
  needs_confirmation: boolean;
  params: {
    ads_conversion_id: string | null;
    ads_conversion_label: string | null;
    uses_google_ads: boolean | null;
    ga4_measurement_id: string | null;
  };
}

export interface MeasurementLayerProgressDto {
  layer: MeasurementLayer;
  total: number;
  done: number;
}

export interface MeasurementPlanDto {
  website_id: string;
  profile: MeasurementProfileDto;
  ga4_connected: boolean;
  gsc_linked: boolean;
  google_connection: GoogleConnectionState;
  /** Identifiants des (au plus) 3 items les plus utiles à faire maintenant. */
  next_actions: string[];
  last_checked_at: string | null;
  overall_done: number;
  overall_total: number;
  overall_percent: number;
  layers: MeasurementLayerProgressDto[];
  items: MeasurementItemDto[];
  /** Vrai quand un passage du navigateur a eu lieu il y a moins de 5 minutes (pas relancé). */
  headless_skipped: boolean;
  /** Erreur du navigateur (texte du service de vérification), null si tout va bien. */
  headless_error: string | null;
  /** Date de la dernière preuve « en conditions réelles » conservée. */
  headless_checked_at: string | null;
}

export interface MeasurementProfilePatch {
  confirmed_types?: SiteType[] | null;
  uses_google_ads?: boolean | null;
  ads_conversion_id?: string | null;
  ads_conversion_label?: string | null;
  ga4_measurement_id?: string | null;
}

export interface MeasurementContainerDto {
  container: Record<string, unknown>;
  warnings: string[];
  filename: string;
  /** Items dont l'événement n'existe que si le site le pousse lui-même. */
  needs_site_code: string[];
}

/** Exactement un des deux : le pack de démarrage OU une sélection explicite. */
export type ContainerSelection =
  | { pack: "starter"; item_ids?: never }
  | { item_ids: string[]; pack?: never };

export type LinkStatus =
  | "linked"
  | "already_linked"
  | "ambiguous"
  | "none"
  | "skipped"
  | "incomplete";

export interface LinkOutcomeDto {
  status: LinkStatus;
  resource_id: string | null;
  candidates: string[];
  /** Texte français décidé par le backend : à afficher tel quel. */
  message: string;
}

export interface AutolinkDto {
  ga4: LinkOutcomeDto;
  gsc: LinkOutcomeDto;
  /** Plan déjà rafraîchi par le backend après une liaison réussie. */
  plan: MeasurementPlanDto;
}

/** Ce que l'interface garde de la dernière auto-liaison. */
export type AutolinkSummary = Pick<AutolinkDto, "ga4" | "gsc">;

const base = (websiteId: string) => `/websites/${websiteId}/measurement-plan`;

/** Au-delà de 5 minutes, les vérifications légères sont relancées à l'ouverture. */
export const STALE_AFTER_MS = 5 * 60 * 1000;

export function isStale(lastCheckedAt: string | null, now: number = Date.now()): boolean {
  if (lastCheckedAt === null) return true;
  const checkedAt = new Date(lastCheckedAt).getTime();
  // Date illisible : on ne sait pas si c'est frais, donc à revérifier.
  if (Number.isNaN(checkedAt)) return true;
  return now - checkedAt > STALE_AFTER_MS;
}

export function fetchMeasurementPlan(websiteId: string): Promise<MeasurementPlanDto> {
  return apiGet<MeasurementPlanDto>(base(websiteId));
}

/** Délai client du mode « en conditions réelles » (vrai navigateur), au-delà des 90 s par défaut. */
export const HEADLESS_TIMEOUT_MS = 180_000;

/** Le mode « en conditions réelles » lance un vrai navigateur : délai client de 3 minutes. */
export function refreshMeasurementPlan(
  websiteId: string,
  headless = false,
): Promise<MeasurementPlanDto> {
  return apiPostSlow<MeasurementPlanDto>(
    `${base(websiteId)}/refresh?headless=${headless ? "true" : "false"}`,
    undefined,
    headless ? HEADLESS_TIMEOUT_MS : undefined,
  );
}

/** Réservé au propriétaire du workspace (403 pour un membre). */
export function patchMeasurementProfile(
  websiteId: string,
  body: MeasurementProfilePatch,
): Promise<MeasurementPlanDto> {
  return apiPatch<MeasurementPlanDto>(`${base(websiteId)}/profile`, body);
}

/**
 * Réservé au propriétaire (403 pour un membre). `dismissed: true` ne se combine pas
 * avec `manual_done` ; `manual_done` n'est accepté que pour les items manuels (400 sinon).
 */
export function patchMeasurementItem(
  websiteId: string,
  itemId: string,
  body: { dismissed?: boolean; manual_done?: boolean },
): Promise<MeasurementPlanDto> {
  return apiPatch<MeasurementPlanDto>(`${base(websiteId)}/items/${itemId}`, body);
}

export function buildMeasurementContainer(
  websiteId: string,
  selection: ContainerSelection,
): Promise<MeasurementContainerDto> {
  return apiPostSlow<MeasurementContainerDto>(`${base(websiteId)}/gtm-container`, selection);
}

/**
 * Relie GA4 et Search Console au domaine (jusqu'à 20 appels Google : délai long).
 * Le backend rafraîchit lui-même le plan après une liaison : ne pas enchaîner de refresh.
 */
export function autolinkGoogle(websiteId: string): Promise<AutolinkDto> {
  return apiPostSlow<AutolinkDto>(`${base(websiteId)}/google-autolink`, undefined);
}

/**
 * Message français pour une erreur d'appel du plan de mesure : une limite de débit (429)
 * ou un refus de droits (403) ne sont pas une API hors ligne.
 */
export function describeMeasurementError(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 429) return "Trop de demandes, réessaie dans un instant.";
    if (error.status === 403) return "Action réservée au propriétaire du workspace.";
    if (error.status === 0) return "Le service est injoignable ou trop lent, réessaie.";
    // FastAPI renvoie un `detail` en liste pour un 422 : `client.ts` ne garde alors que le
    // statut brut en anglais.
    if (error.status === 422) return "Valeur refusée : vérifie le format saisi.";
    if (error.status >= 500) {
      return "Le service a rencontré une erreur, réessaie dans un instant.";
    }
    // 400, 401, 404... : le `detail` est un texte français du backend.
    return error.message;
  }
  return "Une erreur inattendue est survenue, réessaie.";
}
