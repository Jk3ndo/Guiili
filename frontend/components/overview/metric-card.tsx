import { Minus, TrendingDown, TrendingUp } from "lucide-react";

import { formatDelta } from "@/lib/format";
import type { MetricScore, MetricStatus } from "@/lib/mock/types";
import { cn } from "@/lib/utils";

const DOT: Record<MetricStatus, string> = {
  good: "bg-ok",
  warn: "bg-warn",
  bad: "bg-danger",
};

function Trend({ delta, className }: { delta: number; className?: string }) {
  if (delta > 0) return <TrendingUp className={className} />;
  if (delta < 0) return <TrendingDown className={className} />;
  return <Minus className={className} />;
}

export function MetricCard({ metric }: { metric: MetricScore }) {
  return (
    <div className="flex flex-col gap-3 rounded-xl border border-white/[0.08] bg-surface/60 p-5 backdrop-blur-sm">
      <div className="flex items-start justify-between gap-2">
        <span className="text-sm text-ink-muted">{metric.label}</span>
        <span className="inline-flex shrink-0 items-center gap-1 rounded-md border border-white/[0.08] px-1.5 py-0.5 text-2xs font-medium text-ink-muted">
          <Trend delta={metric.delta} className="size-3" />
          {formatDelta(metric.delta)}
        </span>
      </div>

      <span className="font-mono text-3xl font-semibold text-ink tabular-nums">
        {metric.value}
      </span>

      <div className="flex flex-col gap-1 text-sm">
        <span className="flex items-center gap-2 font-medium text-ink">
          <span
            className={cn("size-1.5 shrink-0 rounded-full", DOT[metric.status])}
          />
          <span className="line-clamp-1">{metric.verdict}</span>
        </span>
        <span className="line-clamp-1 text-ink-muted">{metric.hint}</span>
      </div>
    </div>
  );
}
