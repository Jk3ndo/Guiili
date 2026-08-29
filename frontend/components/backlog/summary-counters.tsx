import type { IssueStatus } from "@/lib/mock/backlog";
import { cn } from "@/lib/utils";

const META: { status: IssueStatus; label: string; dot: string }[] = [
  { status: "todo", label: "À corriger", dot: "bg-warn" },
  { status: "in_progress", label: "En cours", dot: "bg-sky-400" },
  { status: "done", label: "Résolus", dot: "bg-ok" },
];

export function SummaryCounters({
  counts,
}: {
  counts: Record<IssueStatus, number>;
}) {
  return (
    <div className="grid grid-cols-3 gap-3">
      {META.map((meta) => (
        <div
          key={meta.status}
          className="rounded-xl border border-white/[0.08] bg-surface/60 p-4 backdrop-blur-sm"
        >
          <div className="flex items-center gap-2">
            <span className={cn("size-1.5 shrink-0 rounded-full", meta.dot)} />
            <span className="text-xs text-ink-muted">{meta.label}</span>
          </div>
          <p className="mt-2 font-mono text-2xl font-semibold text-ink tabular-nums">
            {counts[meta.status]}
          </p>
        </div>
      ))}
    </div>
  );
}
