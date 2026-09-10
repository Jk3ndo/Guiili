import type {
  AuditData,
  Ga4Stream,
  GtmHealth,
  UrlIndexStatus,
  VitalDiagnostic,
  WebVital,
} from "@/lib/mock/audit";
import type {
  IssueCategory,
  IssueItem,
  IssueSeverity,
  IssueStatus,
} from "@/lib/mock/backlog";
import type {
  AuditEventResult,
  MetricScore,
  MetricStatus,
  OverviewData,
  StackId,
} from "@/lib/mock/types";

import type {
  AuditDto,
  AuditVitalDto,
  CwvDiagnosticDto,
  GtmDto,
  IssueDto,
  OverviewDto,
} from "./dto";

const METRIC_STATUS: Record<string, MetricStatus> = {
  good: "good",
  warn: "warn",
  bad: "bad",
};

const VERDICT: Record<MetricStatus, string> = {
  good: "Signal sain",
  warn: "À surveiller",
  bad: "Hors seuil",
};

const STACK: Record<string, StackId> = {
  nextjs: "nextjs",
  wordpress: "wordpress",
  woocommerce: "wordpress",
  nuxt: "vue",
  vue: "vue",
  angular: "angular",
  react: "react",
  vite: "vite",
  php: "php",
  generic: "other",
  unknown: "other",
};

export function mapStack(stack: string | null | undefined): StackId {
  return stack ? (STACK[stack] ?? "other") : "other";
}

export function mapOverview(dto: OverviewDto): OverviewData {
  return {
    siteName: dto.site_name,
    domain: dto.domain,
    stack: mapStack(dto.stack),
    lastScanHoursAgo: dto.last_scan_hours_ago ?? 0,
    metrics: dto.metrics.map((metric): MetricScore => {
      const status = METRIC_STATUS[metric.status] ?? "bad";
      return {
        id: metric.id,
        label: metric.label,
        value: metric.value,
        status,
        delta: 0,
        verdict: VERDICT[status],
        hint: `Score ${metric.score}/100`,
      };
    }),
    recommendation: dto.recommendation
      ? {
          severity: dto.recommendation.severity,
          title: dto.recommendation.title,
          detail: dto.recommendation.detail,
          impact: "Détecté par le dernier diagnostic",
          cta: {
            label:
              dto.recommendation.cta_kind === "gtm"
                ? "Générer le conteneur GTM"
                : "Voir le snippet",
            kind: dto.recommendation.cta_kind,
          },
        }
      : null,
    events: dto.events.map((event) => ({
      id: event.id,
      kind: "scan" as const,
      action: event.action,
      target: event.target,
      result: (event.result === "success"
        ? "success"
        : "error") as AuditEventResult,
      hoursAgo: event.hours_ago,
    })),
  };
}

const CATEGORY: Record<string, IssueCategory> = {
  analytics: "ga4",
  cwv: "vitals",
  seo: "indexation",
  tracking: "gtm",
  other: "gtm",
};

const SEVERITY: Record<string, IssueSeverity> = {
  critical: "critical",
  high: "warning",
  medium: "warning",
  low: "info",
};

const STATUS_FROM_API: Record<string, IssueStatus> = {
  todo: "todo",
  in_progress: "in_progress",
  fixed: "done",
  dismissed: "done",
};

/** Statut UI -> statut backend accepté par PATCH. */
export const STATUS_TO_API: Record<IssueStatus, string> = {
  todo: "todo",
  in_progress: "in_progress",
  done: "resolved",
};

/**
 * Map a backend CWV diagnostic (snake_case) to the mock-shaped union the
 * inspection drawer renders. Returns `undefined` when the payload is null so
 * the card stays non-clickable rather than opening an empty drawer.
 */
export function mapDiagnostic(
  dto: CwvDiagnosticDto | null | undefined,
): VitalDiagnostic | undefined {
  if (!dto) return undefined;
  const recommendations = dto.recommendations ?? [];

  if (dto.metric === "inp") {
    return {
      kind: "inp",
      source: dto.source,
      totalBlockingTimeMs: dto.total_blocking_time_ms ?? 0,
      jsExecutionMs: dto.js_execution_ms ?? 0,
      entities: (dto.entities ?? []).map((entity) => ({
        name: entity.name,
        category: entity.category,
        mainThreadMs: entity.main_thread_ms,
        blockingMs: entity.blocking_ms,
      })),
      recommendations,
    };
  }

  if (dto.metric === "lcp") {
    return {
      kind: "lcp",
      source: dto.source,
      elementSnippet: dto.element_snippet ?? "",
      assets: (dto.assets ?? []).map((asset) => ({
        name: asset.name,
        currentFormat: asset.current_format,
        sizeKb: asset.size_kb,
        estimatedSavingKb: asset.estimated_saving_kb,
      })),
      preloadHint: dto.preload_hint ?? "",
      recommendations,
    };
  }

  return {
    kind: "cls",
    source: dto.source,
    elements: (dto.shift_elements ?? []).map((element) => ({
      selector: element.selector,
      impact: element.impact,
      note: element.note,
    })),
    recommendations,
  };
}

const VITAL_RATING: Record<string, WebVital["rating"]> = {
  good: "good",
  warn: "warn",
  bad: "bad",
};

export function mapAuditVital(dto: AuditVitalDto): WebVital {
  const diagnostic = mapDiagnostic(dto.diagnostic);
  const vital: WebVital = {
    id: dto.id,
    label: dto.label,
    value: dto.value,
    raw: dto.raw,
    rating: VITAL_RATING[dto.rating] ?? "bad",
    target: dto.target,
    thresholds: dto.thresholds,
    hint: dto.hint,
  };
  return diagnostic ? { ...vital, diagnostic } : vital;
}

const GA4_STREAM_STATUS: Record<string, Ga4Stream["status"]> = {
  good: "active",
  warn: "degraded",
  bad: "down",
};

function mapGtm(dto: GtmDto | null): GtmHealth | null {
  if (!dto) return null;
  return {
    containers: dto.containers,
    snippetForm: dto.snippet_form,
    snippetInHead: dto.snippet_in_head,
    dataLayerName: dto.data_layer_name,
    consentPlatform: dto.consent_platform,
    serverSide: dto.server_side,
    cspBlocksPreview: dto.csp_blocks_preview,
    findings: dto.findings.map((f) => ({
      code: f.code,
      severity: f.severity,
      title: f.title,
      detail: f.detail,
    })),
    checked: dto.checked,
  };
}

/** Backend `GET /websites/{id}/audit` payload -> the shape `/audit` renders. */
export function mapAudit(dto: AuditDto): AuditData {
  return {
    ga4: {
      status: GA4_STREAM_STATUS[dto.ga4.status] ?? "down",
      statusLine: dto.ga4.status_line,
      property: dto.ga4.property ?? "—",
      events: dto.ga4.events.map((event) => ({
        name: event.name,
        conformity: event.conformity,
        volume: event.volume,
        note: event.note,
      })),
    },
    index: {
      property: dto.index.property ?? "—",
      valid: dto.index.valid,
      excluded: dto.index.excluded,
      reasons: dto.index.reasons.map((reason) => ({
        label: reason.label,
        urls: reason.urls,
      })),
    },
    urls: dto.urls.map((entry) => ({
      url: entry.url,
      status: entry.status as UrlIndexStatus,
      clicks: entry.clicks,
      impressions: entry.impressions,
      ctr: entry.ctr,
      marketingAction: entry.marketing_action,
    })),
    vitals: dto.vitals.map(mapAuditVital),
    gtm: mapGtm(dto.gtm),
  };
}

export function mapIssue(dto: IssueDto): IssueItem {
  const detectedMs = Date.parse(dto.detected_at);
  const days = Number.isNaN(detectedMs)
    ? 0
    : Math.max(0, Math.round((Date.now() - detectedMs) / 86_400_000));

  return {
    id: dto.id,
    title: dto.title,
    context: dto.description,
    impact: "Impact estimé par le diagnostic.",
    category: CATEGORY[dto.category] ?? "gtm",
    severity: SEVERITY[dto.severity] ?? "warning",
    status: STATUS_FROM_API[dto.status] ?? "todo",
    detectedDaysAgo: days,
    fix: { summary: dto.description },
  };
}
