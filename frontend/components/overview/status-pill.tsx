import { cn } from "@/lib/utils";
import type { MetricStatus } from "@/lib/mock/types";

const META: Record<MetricStatus, { label: string; dot: string }> = {
  good: { label: "Bon", dot: "bg-ok" },
  warn: { label: "À surveiller", dot: "bg-warn" },
  bad: { label: "Critique", dot: "bg-danger" },
};

/** Flat 6px dot + neutral label. No ring, no tint, no glow. */
export function StatusPill({
  status,
  className,
}: {
  status: MetricStatus;
  className?: string;
}) {
  const m = META[status];
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 text-xs text-ink-muted",
        className,
      )}
    >
      <span className={cn("size-1.5 rounded-full", m.dot)} />
      {m.label}
    </span>
  );
}
