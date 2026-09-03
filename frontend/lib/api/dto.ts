/** Formes de réponse du backend FastAPI (snake_case, telles quelles). */

export interface DevWorkspaceDto {
  id: string;
  domain: string;
  display_name: string;
  detected_stack: string | null;
}

export interface WebsiteDto {
  id: string;
  domain: string;
  display_name: string;
  detected_stack: string | null;
  stack_label: string | null;
  allow_insecure_probe: boolean;
  ssl_status: string | null;
  ssl_expires_at: string | null;
  ssl_checked_at: string | null;
  archived_at: string | null;
}

export interface StackGuessDto {
  label: string;
  reason: string;
}

export interface StackDetectionDto {
  stack: string;
  confidence: number;
  signals: string[];
  candidates: StackGuessDto[];
  error: string | null;
}

export interface SslDto {
  status: string | null;
  expires_at: string | null;
  checked_at: string | null;
}

export interface CreateWebsiteDto {
  id: string;
  domain: string;
  display_name: string;
  detected_stack: string | null;
  stack_label: string | null;
  detection: StackDetectionDto;
  ssl: SslDto;
  snapshot_id: string;
  captured_at: string;
  metrics: Record<string, unknown>;
  issues: { created: number; updated: number; resolved: number };
}

export interface StackHintDto {
  detected_stack: string | null;
  stack_label: string | null;
  confidence: number;
  candidates: StackGuessDto[];
  error: string | null;
  needs_confirmation: boolean;
}

export interface RedetectDto {
  detected_stack: string | null;
  detection: StackDetectionDto;
}

export interface OverviewMetricDto {
  id: "ga4" | "gsc" | "cwv";
  label: string;
  value: string;
  score: number;
  status: "good" | "warn" | "bad";
}

export interface OverviewRecommendationDto {
  severity: "high" | "medium";
  title: string;
  detail: string;
  cta_kind: "gtm" | "snippet";
}

export interface OverviewEventDto {
  id: string;
  kind: string;
  action: string;
  target: string;
  result: string;
  hours_ago: number;
}

export interface OverviewDto {
  site_name: string;
  domain: string;
  stack: string | null;
  last_scan_hours_ago: number | null;
  metrics: OverviewMetricDto[];
  recommendation: OverviewRecommendationDto | null;
  events: OverviewEventDto[];
}

export interface IssueDto {
  id: string;
  title: string;
  description: string;
  category: string;
  severity: string;
  status: string;
  fingerprint: string;
  detected_at: string;
  resolved_at: string | null;
}

export interface ScanDto {
  snapshot_id: string;
  detected_stack: string;
  metrics: Record<string, unknown>;
  issues: { created: number; updated: number; resolved: number };
}

export interface SnippetEntryDto {
  stack: string;
  event: "purchase" | "lead" | "custom";
  language: string;
  code: string;
  target_path: string;
  instructions: string;
}

export interface SnippetsDto {
  detected_stack: string | null;
  resolved_stack: string;
  entries: SnippetEntryDto[];
}

/* -------------------------------------------------------------------------- */
/*  Audit — detailed Core Web Vitals diagnostics (PageSpeed probe, P2)        */
/* -------------------------------------------------------------------------- */

export interface CwvEntityDto {
  name: string;
  category: string;
  main_thread_ms: number;
  blocking_ms: number;
}

export interface CwvAssetDto {
  name: string;
  current_format: string;
  size_kb: number;
  estimated_saving_kb: number;
}

export interface CwvShiftElementDto {
  selector: string;
  impact: number;
  note: string;
}

export interface CwvDiagnosticDto {
  metric: "lcp" | "inp" | "cls";
  /** "field" = CrUX real-user data, "lab" = synthetic Lighthouse audit. */
  source: "field" | "lab";
  total_blocking_time_ms?: number;
  js_execution_ms?: number;
  entities?: CwvEntityDto[];
  element_snippet?: string;
  assets?: CwvAssetDto[];
  preload_hint?: string;
  shift_elements?: CwvShiftElementDto[];
  recommendations: string[];
}

export interface AuditVitalDto {
  id: "lcp" | "inp" | "cls";
  label: string;
  value: string;
  raw: number;
  rating: "good" | "warn" | "bad";
  target: string;
  thresholds: [number, number];
  hint: string;
  diagnostic: CwvDiagnosticDto | null;
}

export interface AuditGa4EventDto {
  name: string;
  conformity: "conforme" | "partial" | "missing";
  note: string;
  volume: number;
}

export interface AuditGa4Dto {
  score: number;
  status: "good" | "warn" | "bad";
  status_line: string;
  property: string | null;
  events: AuditGa4EventDto[];
}

export interface AuditIndexReasonDto {
  label: string;
  urls: number;
}

export interface AuditIndexDto {
  property: string | null;
  valid: number;
  excluded: number;
  reasons: AuditIndexReasonDto[];
}

export interface AuditUrlDto {
  url: string;
  status: string;
  clicks: number;
  impressions: number;
  ctr: number;
  marketing_action: string;
}

export interface AuditDto {
  site_name: string;
  domain: string;
  captured_at: string | null;
  ga4: AuditGa4Dto;
  index: AuditIndexDto;
  urls: AuditUrlDto[];
  vitals: AuditVitalDto[];
}
