import type { ReactNode } from "react";

export function BoardColumn({
  label,
  count,
  children,
}: {
  label: string;
  count: number;
  children: ReactNode;
}) {
  return (
    <section className="flex min-w-0 flex-col rounded-xl border border-white/[0.06] bg-surface/25 p-2.5">
      <header className="flex items-center gap-2 px-1.5 pt-1 pb-2.5">
        <h2 className="text-xs font-medium text-ink">{label}</h2>
        <span className="rounded bg-white/[0.06] px-1.5 font-mono text-2xs text-ink-muted tabular-nums">
          {count}
        </span>
      </header>
      <div className="flex flex-1 flex-col gap-2">{children}</div>
    </section>
  );
}
