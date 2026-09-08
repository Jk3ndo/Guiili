/**
 * Shapes the shell renders today from local fixtures. When the API lands,
 * only `lib/mock/*` gets swapped — components import from here, not from fetch.
 */

export type StackId =
  | "nextjs"
  | "wordpress"
  | "angular"
  | "vue"
  | "react"
  | "vite"
  | "php"
  | "other";

export type TokenStatus = "connected" | "needs_reauth";

export type SslStatus =
  | "valid"
  | "expiring_soon"
  | "expired"
  | "self_signed"
  | "hostname_mismatch"
  | "untrusted"
  | "unreachable";

export interface Workspace {
  id: string;
  /** Display name for the tracked site. */
  name: string;
  /** Bare domain, e.g. "boutique-verte.fr". */
  domain: string;
  /** Detected front-end stack — drives the sidebar badge. */
  stack: StackId;
  /** Health of the Google connection(s) backing this site. */
  tokenStatus: TokenStatus;
  /** Backend UUID for a real site added by the user (undefined for demo sites). */
  websiteId?: string;
  /** User-confirmed stack (free text) — overrides the badge when set. */
  stackLabel?: string | null;
  /** Latest HTTPS certificate status (real sites only). */
  sslStatus?: SslStatus | null;
  sslExpiresAt?: string | null;
}

/* -------------------------------------------------------------------------- */
/*  Overview view                                                            */
/* -------------------------------------------------------------------------- */

export type MetricStatus = "good" | "warn" | "bad";

export interface MetricScore {
  id: "ga4" | "gsc" | "cwv";
  label: string;
  /** Rendered as-is, in Geist Mono. e.g. "92", "68 %". */
  value: string;
  status: MetricStatus;
  /** Percentage-point change vs. the previous month. */
  delta: number;
  /** Short verdict line (font-medium) — the current-state read. */
  verdict: string;
  /** Muted context line under the verdict. */
  hint: string;
}

export interface PriorityRecommendation {
  severity: "high" | "medium";
  title: string;
  detail: string;
  /** Estimated impact, e.g. "≈ 40 % des conversions non attribuées". */
  impact: string;
  cta: { label: string; kind: "gtm" | "snippet" };
}

export type AuditEventKind = "scan" | "export" | "snippet" | "connection";
export type AuditEventResult = "success" | "error";

export interface AuditEvent {
  id: string;
  kind: AuditEventKind;
  action: string;
  /** What the action touched — a container id, a path, a domain. */
  target: string;
  result: AuditEventResult;
  /** Hours before "now" — kept relative (not a timestamp) so the mock is
   *  deterministic and never triggers a hydration mismatch. */
  hoursAgo: number;
}

export interface OverviewData {
  siteName: string;
  domain: string;
  stack: StackId;
  /** Hours since the last completed diagnostic. */
  lastScanHoursAgo: number;
  metrics: MetricScore[];
  recommendation: PriorityRecommendation | null;
  events: AuditEvent[];
}
