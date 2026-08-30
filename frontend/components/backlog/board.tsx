"use client";

import {
  closestCorners,
  DndContext,
  DragOverlay,
  PointerSensor,
  useSensor,
  useSensors,
  type DragEndEvent,
  type DragOverEvent,
  type DragStartEvent,
} from "@dnd-kit/core";
import { arrayMove } from "@dnd-kit/sortable";
import { Plus } from "lucide-react";
import { useMemo, useRef, useState } from "react";
import { toast } from "sonner";

import type { HighlightedFixes } from "@/lib/backlog/highlight";
import {
  STATUS_LABEL,
  STATUS_ORDER,
  type IssueItem,
  type IssueStatus,
} from "@/lib/mock/backlog";

import { AddIssueDialog, type NewIssueDraft } from "./add-issue-dialog";
import { BoardCard, BoardCardOverlay } from "./board-card";
import { BoardColumn } from "./board-column";
import { FiltersBar, type BacklogFilters } from "./filters-bar";
import { IssueDrawer } from "./issue-drawer";

function isStatus(value: string): value is IssueStatus {
  return (STATUS_ORDER as string[]).includes(value);
}

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
  const [activeId, setActiveId] = useState<string | null>(null);

  const draggedRef = useRef(false);
  const originRef = useRef<{ status: IssueStatus; snapshot: IssueItem[] } | null>(
    null,
  );

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 8 } }),
  );

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
  const activeItem = activeId
    ? (tickets.find((ticket) => ticket.id === activeId) ?? null)
    : null;

  function resolveTargetStatus(overId: string): IssueStatus | undefined {
    if (isStatus(overId)) return overId;
    return tickets.find((ticket) => ticket.id === overId)?.status;
  }

  function moveStatus(id: string, status: IssueStatus) {
    const ticket = tickets.find((candidate) => candidate.id === id);
    if (!ticket || ticket.status === status) return;
    setTickets((prev) =>
      prev.map((candidate) =>
        candidate.id === id ? { ...candidate, status } : candidate,
      ),
    );
    toast("Ticket déplacé", {
      description: `${ticket.title} → ${STATUS_LABEL[status]}`,
    });
  }

  function handleDragStart(event: DragStartEvent) {
    const id = String(event.active.id);
    const ticket = tickets.find((candidate) => candidate.id === id);
    draggedRef.current = true;
    originRef.current = ticket
      ? { status: ticket.status, snapshot: tickets }
      : null;
    setActiveId(id);
  }

  function handleDragOver(event: DragOverEvent) {
    const { active, over } = event;
    if (!over) return;
    const activeCardId = String(active.id);
    const activeCard = tickets.find((ticket) => ticket.id === activeCardId);
    if (!activeCard) return;

    const targetStatus = resolveTargetStatus(String(over.id));
    if (!targetStatus || activeCard.status === targetStatus) return;

    setTickets((prev) => {
      const moved = prev.map((ticket) =>
        ticket.id === activeCardId ? { ...ticket, status: targetStatus } : ticket,
      );
      if (isStatus(String(over.id))) return moved;
      const from = moved.findIndex((ticket) => ticket.id === activeCardId);
      const to = moved.findIndex((ticket) => ticket.id === String(over.id));
      return from === -1 || to === -1 ? moved : arrayMove(moved, from, to);
    });
  }

  function endDrag() {
    setActiveId(null);
    originRef.current = null;
    window.setTimeout(() => {
      draggedRef.current = false;
    }, 0);
  }

  function handleDragEnd(event: DragEndEvent) {
    const { active, over } = event;
    const activeCardId = String(active.id);
    const origin = originRef.current;

    if (over) {
      const overId = String(over.id);
      if (!isStatus(overId)) {
        setTickets((prev) => {
          const from = prev.findIndex((ticket) => ticket.id === activeCardId);
          const to = prev.findIndex((ticket) => ticket.id === overId);
          return from === -1 || to === -1 ? prev : arrayMove(prev, from, to);
        });
      }
    }

    const finalStatus = tickets.find(
      (ticket) => ticket.id === activeCardId,
    )?.status;
    if (origin && finalStatus && finalStatus !== origin.status) {
      const ticket = tickets.find((candidate) => candidate.id === activeCardId);
      if (ticket) {
        toast("Ticket déplacé", {
          description: `${ticket.title} → ${STATUS_LABEL[finalStatus]}`,
        });
      }
    }

    endDrag();
  }

  function handleDragCancel() {
    if (originRef.current) setTickets(originRef.current.snapshot);
    endDrag();
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
        ...(draft.snippet ? { code: draft.snippet, lang: "ts" as const } : {}),
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

      <DndContext
        id="backlog-board"
        sensors={sensors}
        collisionDetection={closestCorners}
        onDragStart={handleDragStart}
        onDragOver={handleDragOver}
        onDragEnd={handleDragEnd}
        onDragCancel={handleDragCancel}
      >
        <div className="grid gap-4 md:grid-cols-3">
          {STATUS_ORDER.map((status) => (
            <BoardColumn
              key={status}
              status={status}
              label={STATUS_LABEL[status]}
              count={byStatus[status].length}
              cardIds={byStatus[status].map((ticket) => ticket.id)}
            >
              {byStatus[status].length === 0 ? (
                <p className="grid flex-1 place-items-center rounded-lg border border-dashed border-white/[0.08] px-3 py-6 text-center text-2xs text-ink-faint">
                  Déposez un ticket ici
                </p>
              ) : (
                byStatus[status].map((item) => (
                  <BoardCard
                    key={item.id}
                    item={item}
                    onOpen={(id) => {
                      if (!draggedRef.current) setSelectedId(id);
                    }}
                    onStatusChange={moveStatus}
                  />
                ))
              )}
            </BoardColumn>
          ))}
        </div>

        <DragOverlay>
          {activeItem ? <BoardCardOverlay item={activeItem} /> : null}
        </DragOverlay>
      </DndContext>

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
