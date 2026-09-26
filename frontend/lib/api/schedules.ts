import { ApiError, apiGet, apiPut } from "./client";

// Types alignés sur `backend/app/api/v1/endpoints/metrics.py` (le backend fait foi).

export type ScheduleKind =
  | "collect_ga4"
  | "collect_gsc"
  | "collect_cwv"
  | "collect_probes"
  | "measurement_check";

export type ScheduleFrequency =
  | "hourly"
  | "three_daily"
  | "daily"
  | "every_3_days"
  | "weekly";

export type RunStatus = "queued" | "running" | "succeeded" | "failed" | "skipped";

export interface ScheduleDto {
  kind: ScheduleKind;
  label: string;
  frequency: ScheduleFrequency;
  enabled: boolean;
  /** Fréquences permises par le plancher de la source (quotas Google : 8 h). */
  allowed_frequencies: ScheduleFrequency[];
  floor_hours: number;
  next_due_at: string | null;
  last_run_at: string | null;
  last_status: RunStatus | null;
  last_success_at: string | null;
  failing_since: string | null;
  last_error_code: string | null;
  /** Texte français décidé par le backend : à afficher tel quel. */
  last_error: string | null;
  backfill_done_at: string | null;
}

export interface SchedulesDto {
  website_id: string;
  /** Vrai seulement pour le propriétaire du workspace (le backend fait foi). */
  can_edit: boolean;
  frequency_labels: Record<ScheduleFrequency, string>;
  schedules: ScheduleDto[];
}

export interface ScheduleUpdate {
  kind: ScheduleKind;
  frequency: ScheduleFrequency;
  enabled: boolean;
}

export function fetchSchedules(websiteId: string): Promise<SchedulesDto> {
  return apiGet<SchedulesDto>(`/websites/${websiteId}/schedules`);
}

/** Réservé au propriétaire (403 pour un membre). */
export function updateSchedule(websiteId: string, body: ScheduleUpdate): Promise<SchedulesDto> {
  return apiPut<SchedulesDto>(`/websites/${websiteId}/schedules`, body);
}

/**
 * Message français pour une erreur du suivi automatique : une limite de débit (429), un
 * refus de droits (403) ou une panne (5xx) ne sont jamais présentés comme « API hors ligne ».
 */
export function describeScheduleError(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 429) return "Trop de demandes, réessaie dans un instant.";
    if (error.status === 403) {
      return "Seul le propriétaire du workspace peut modifier le suivi automatique.";
    }
    if (error.status === 0) return "Le service est injoignable ou trop lent, réessaie.";
    if (error.status === 422) {
      return "Fréquence refusée : elle est plus rapide que ce que permet cette source.";
    }
    if (error.status >= 500) {
      return "Le service a rencontré une erreur, réessaie dans un instant.";
    }
    return error.message;
  }
  return "Une erreur inattendue est survenue, réessaie.";
}
