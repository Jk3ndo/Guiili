"use client";

import { Plus } from "lucide-react";
import { useMemo, useState } from "react";
import { toast } from "sonner";

import type { HighlightedFixes } from "@/lib/backlog/highlight";
import {
  STATUS_LABEL,
  STATUS_ORDER,
  type IssueItem,
  type IssueStatus,
} from "@/lib/mock/backlog";

import { AddIssueDialog, type NewIssueDraft } from "./add-issue-dialog";
import { BoardCard } from "./board-card";
import { BoardColumn } from "./board-column";
import { FiltersBar, type BacklogFilters } from "./filters-bar";
import { IssueDrawer } from "./issue-drawer";

const COLUMN_LABEL: Record<IssueStatus, string> = STATUS_LABEL;

function emptyGroups(): Record<IssueStatus, IssueItem[]> {
  return { todo: [], in_progress: [], done: [] };
}

export function Board({
  items,
  highlighted,
}: {
  items: IssueItem[];
  highlighted: HighlightedFixes;
}) {
  const [tickets, setTickets] = useState<IssueItem[]>(items);
  const [filters, setFilters] = useState<BacklogFilters>({
    query: "",
    category: "all",
    severity: "all",
  });
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);

  const byStatus = useMemo(() => {
    const query = filters.query.trim().toLowerCase();
    const groups = emptyGroups();
    for (const ticket of tickets) {
      if (filters.category !== "all" && ticket.category !== filters.category) {
        continue;
      }
      if (filters.severity !== "all" && ticket.severity !== filters.severity) {
        continue;
      }
      if (
        query &&
        !`${ticket.title} ${ticket.context}`.toLowerCase().includes(query)
      ) {
        continue;
      }
      groups[ticket.status].push(ticket);
    }
    return groups;
  }, [tickets, filters]);

  const selected = selectedId
    ? (tickets.find((ticket) => ticket.id === selectedId) ?? null)
    : null;

  function changeStatus(id: string, next: IssueStatus) {
    const ticket = tickets.find((candidate) => candidate.id === id);
    setTickets((prev) =>
      prev.map((candidate) =>
        candidate.id === id ? { ...candidate, status: next } : candidate,
      ),
    );
    toast("Statut mis à jour", {
      description: `${ticket?.title ?? id} → ${STATUS_LABEL[next]}`,
    });
  }

  function createTicket(draft: NewIssueDraft) {
    const ticket: IssueItem = {
      id: `user-${Date.now()}`,
      title: draft.title,
      context: draft.note || "Anomalie ajoutée manuellement.",
      impact: "Impact à qualifier.",
      category: draft.category,
      severity: draft.severity,
      status: "todo",
      detectedDaysAgo: 0,
      fix: {
        summary: draft.note || "À documenter.",
        ...(draft.snippet
          ? { code: draft.snippet, lang: "ts" as const }
          : {}),
      },
    };
    setTickets((prev) => [ticket, ...prev]);
    toast("Anomalie ajoutée", {
      description: `${draft.title} — colonne « À traiter »`,
    });
  }

  return (
    <>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <FiltersBar filters={filters} onChange={setFilters} />
        <button
          type="button"
          onClick={() => setAdding(true)}
          className="inline-flex h-9 shrink-0 items-center gap-1.5 rounded-lg border border-white/[0.08] bg-white/[0.03] px-3.5 text-xs font-medium text-ink-muted shadow-sm transition-colors hover:bg-white/[0.06] hover:text-ink"
        >
          <Plus className="size-3.5" />
          Ajouter une anomalie
        </button>
      </div>

      <div className="grid gap-4 md:grid-cols-3">
        {STATUS_ORDER.map((status) => (
          <BoardColumn
            key={status}
            label={COLUMN_LABEL[status]}
            count={byStatus[status].length}
          >
            {byStatus[status].length === 0 ? (
              <p className="rounded-lg border border-dashed border-white/[0.08] px-3 py-6 text-center text-2xs text-ink-faint">
                Aucun ticket
              </p>
            ) : (
              byStatus[status].map((item) => (
                <BoardCard
                  key={item.id}
                  item={item}
                  onOpen={setSelectedId}
                  onStatusChange={changeStatus}
                />
              ))
            )}
          </BoardColumn>
        ))}
      </div>

      <IssueDrawer
        item={selected}
        tokens={selected ? highlighted[selected.id] : undefined}
        onOpenChange={(open) => {
          if (!open) setSelectedId(null);
        }}
      />
      <AddIssueDialog
        open={adding}
        onOpenChange={setAdding}
        onCreate={createTicket}
      />
    </>
  );
}
