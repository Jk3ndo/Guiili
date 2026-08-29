import { cn } from "@/lib/utils";
import type { MetricStatus } from "@/lib/mock/types";

const META: Record<MetricStatus, { label: string; tone: string; dot: string }> =
  {
    good: {
      label: "Bon",
      tone: "text-ok ring-ok/25 bg-ok/[0.08]",
      dot: "bg-ok shadow-[0_0_6px_1px] shadow-ok/70",
    },
    warn: {
      label: "À surveiller",
      tone: "text-warn ring-warn/25 bg-warn/[0.08]",
      dot: "bg-warn shadow-[0_0_6px_1px] shadow-warn/70",
    },
    bad: {
      label: "Critique",
      tone: "text-danger ring-danger/25 bg-danger/[0.08]",
      dot: "bg-danger shadow-[0_0_6px_1px] shadow-danger/70",
    },
  };

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
        "inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-2xs font-medium ring-1 ring-inset",
        m.tone,
        className,
      )}
    >
      <span className={cn("size-1.5 rounded-full", m.dot)} />
      {m.label}
    </span>
  );
}
