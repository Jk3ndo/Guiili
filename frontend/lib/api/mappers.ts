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

import type { IssueDto, OverviewDto } from "./dto";

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
