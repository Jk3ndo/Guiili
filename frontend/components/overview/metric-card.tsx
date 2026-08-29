import { Minus, TrendingDown, TrendingUp } from "lucide-react";

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
  const DeltaIcon =
    metric.delta > 0 ? TrendingUp : metric.delta < 0 ? TrendingDown : Minus;

  return (
    <div className="flex flex-col gap-3 rounded-lg border border-hairline bg-surface p-4">
      <div className="flex items-center justify-between">
        <span className="text-xs text-ink-muted">{metric.label}</span>
        <StatusPill status={metric.status} />
      </div>

      <div className="flex items-baseline gap-2">
        <span className="font-mono text-2xl leading-none font-medium text-ink tabular-nums">
          {metric.value}
        </span>
        <span
          className={cn(
            "inline-flex items-center gap-0.5 text-2xs font-medium",
            deltaTone(metric.delta),
          )}
        >
          <DeltaIcon className="size-3" />
          {formatDelta(metric.delta)}
        </span>
      </div>

      <p className="text-2xs leading-snug text-ink-faint">{metric.hint}</p>
    </div>
  );
}
