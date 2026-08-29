import { formatDelta } from "@/lib/format";
import type { MetricScore } from "@/lib/mock/types";
import { cn } from "@/lib/utils";

import { StatusPill } from "./status-pill";

/** Higher score = better for every metric, so a positive delta is always good. */
function deltaTone(delta: number): string {
  if (delta > 0) return "text-ok";
  if (delta < 0) return "text-danger";
  return "text-ink-faint";
}

export function MetricCard({ metric }: { metric: MetricScore }) {
  return (
    <div className="rounded-xl border border-white/[0.08] bg-surface/60 p-5 backdrop-blur-sm">
      <div className="flex items-center justify-between">
        <span className="text-sm text-ink-muted">{metric.label}</span>
        <StatusPill status={metric.status} />
      </div>

      <div className="mt-3.5 flex items-baseline gap-2.5">
        <span className="font-mono text-3xl font-semibold text-ink tabular-nums">
          {metric.value}
        </span>
        <span className={cn("text-xs font-medium", deltaTone(metric.delta))}>
          {formatDelta(metric.delta)}
        </span>
      </div>

      <p className="mt-2 text-xs leading-relaxed text-ink-muted">
        {metric.hint}
      </p>
    </div>
  );
}
