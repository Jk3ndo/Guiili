/** Formes de réponse du backend FastAPI (snake_case, telles quelles). */

export interface DevWorkspaceDto {
  id: string;
  domain: string;
  display_name: string;
  detected_stack: string | null;
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
