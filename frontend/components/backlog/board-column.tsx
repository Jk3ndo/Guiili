"use client";

import { useDroppable } from "@dnd-kit/core";
import {
  SortableContext,
  verticalListSortingStrategy,
} from "@dnd-kit/sortable";
import type { ReactNode } from "react";

import type { IssueStatus } from "@/lib/mock/backlog";
import { cn } from "@/lib/utils";

export function BoardColumn({
  status,
  label,
  count,
  cardIds,
  children,
}: {
  status: IssueStatus;
  label: string;
  count: number;
  cardIds: string[];
  children: ReactNode;
}) {
  const { setNodeRef, isOver } = useDroppable({ id: status });

  return (
    <section
      ref={setNodeRef}
      className={cn(
        "flex min-w-0 flex-col rounded-xl border p-2.5 transition-colors",
        isOver
          ? "border-white/[0.16] bg-surface/40"
          : "border-white/[0.06] bg-surface/25",
      )}
    >
      <header className="flex items-center gap-2 px-1.5 pt-1 pb-2.5">
        <h2 className="text-xs font-medium text-ink">{label}</h2>
        <span className="rounded bg-white/[0.06] px-1.5 font-mono text-2xs text-ink-muted tabular-nums">
          {count}
        </span>
      </header>
      <SortableContext items={cardIds} strategy={verticalListSortingStrategy}>
        <div className="flex min-h-24 flex-1 flex-col gap-2">{children}</div>
      </SortableContext>
    </section>
  );
}
