"use client";

import { useMemo, useState } from "react";
import { toast } from "sonner";

import type { HighlightedFixes } from "@/lib/backlog/highlight";
import {
  STATUS_LABEL,
  type IssueItem,
  type IssueStatus,
} from "@/lib/mock/backlog";

import { FiltersBar, type BacklogFilters } from "./filters-bar";
import { IssueCard } from "./issue-card";
import { SummaryCounters } from "./summary-counters";

const EMPTY_COUNTS: Record<IssueStatus, number> = {
  todo: 0,
  in_progress: 0,
  done: 0,
};

export function Backlog({
  items,
  highlighted,
}: {
  items: IssueItem[];
  highlighted: HighlightedFixes;
}) {
  const [statuses, setStatuses] = useState<Record<string, IssueStatus>>(() =>
    Object.fromEntries(items.map((item) => [item.id, item.status])),
  );
  const [filters, setFilters] = useState<BacklogFilters>({
    query: "",
    category: "all",
    severity: "all",
  });

  const counts = useMemo(() => {
    const next = { ...EMPTY_COUNTS };
    for (const item of items) next[statuses[item.id] ?? item.status] += 1;
    return next;
  }, [items, statuses]);

  const visible = useMemo(() => {
    const query = filters.query.trim().toLowerCase();
    return items.filter((item) => {
      if (filters.category !== "all" && item.category !== filters.category) {
        return false;
      }
      if (filters.severity !== "all" && item.severity !== filters.severity) {
        return false;
      }
      if (
        query &&
        !`${item.title} ${item.context}`.toLowerCase().includes(query)
      ) {
        return false;
      }
      return true;
    });
  }, [items, filters]);

  function handleStatusChange(id: string, next: IssueStatus) {
    setStatuses((prev) => ({ ...prev, [id]: next }));
    const item = items.find((candidate) => candidate.id === id);
    toast("Statut mis à jour", {
      description: `${item?.title ?? id} → ${STATUS_LABEL[next]}`,
    });
  }

  return (
    <>
      <SummaryCounters counts={counts} />
      <FiltersBar filters={filters} onChange={setFilters} />

      {visible.length === 0 ? (
        <p className="rounded-xl border border-dashed border-white/[0.1] bg-surface/30 px-5 py-10 text-center text-xs text-ink-muted">
          Aucun correctif ne correspond à ces filtres.
        </p>
      ) : (
        <div className="space-y-3">
          {visible.map((item) => (
            <IssueCard
              key={item.id}
              item={item}
              status={statuses[item.id] ?? item.status}
              tokens={highlighted[item.id]}
              onStatusChange={handleStatusChange}
            />
          ))}
        </div>
      )}
    </>
  );
}
