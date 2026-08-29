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
    <div className="flex flex-col gap-2 rounded-lg border border-hairline bg-surface p-3.5">
      <div className="flex items-center justify-between">
        <span className="text-xs text-ink-muted">{metric.label}</span>
        <StatusPill status={metric.status} />
      </div>

      <div className="flex items-baseline gap-2">
        <span className="font-mono text-[26px] leading-none font-medium text-ink tabular-nums">
          {metric.value}
        </span>
        <span className={cn("text-2xs font-medium", deltaTone(metric.delta))}>
          {formatDelta(metric.delta)}
        </span>
      </div>

      <p className="text-2xs leading-snug text-ink-faint">{metric.hint}</p>
    </div>
  );
}
