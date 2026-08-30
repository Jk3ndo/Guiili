"use client";

import { useSortable } from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { Code2, MoreHorizontal } from "lucide-react";

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  CATEGORY_LABEL,
  STATUS_LABEL,
  STATUS_ORDER,
  type IssueItem,
  type IssueSeverity,
  type IssueStatus,
} from "@/lib/mock/backlog";
import { cn } from "@/lib/utils";

const SEVERITY_DOT: Record<IssueSeverity, string> = {
  critical: "bg-danger",
  warning: "bg-warn",
  info: "bg-ink-faint",
};

const CARD_CLASS = "rounded-lg border border-white/[0.08] bg-surface/60 p-3";

function CardBody({ item, menu }: { item: IssueItem; menu?: React.ReactNode }) {
  const resolved = item.status === "done";
  return (
    <>
      <div className="flex items-start gap-2">
        <span
          className={cn(
            "mt-1 size-1.5 shrink-0 rounded-full",
            SEVERITY_DOT[item.severity],
          )}
        />
        <p
          className={cn(
            "flex-1 text-xs leading-snug font-medium text-ink",
            resolved && "text-ink-muted line-through decoration-white/25",
          )}
        >
          {item.title}
        </p>
        {menu}
      </div>
      <div className="mt-2 flex flex-wrap items-center gap-x-2 gap-y-1 pl-3.5">
        <span className="inline-flex h-[18px] items-center rounded border border-hairline bg-white/[0.03] px-1.5 font-mono text-2xs text-ink-muted">
          {CATEGORY_LABEL[item.category]}
        </span>
        {item.fix.code && (
          <span className="inline-flex items-center gap-1 text-2xs text-ink-faint">
            <Code2 className="size-3" />
            Snippet disponible
          </span>
        )}
      </div>
    </>
  );
}

/** Floating clone rendered in the DragOverlay while a card is dragged. */
export function BoardCardOverlay({ item }: { item: IssueItem }) {
  return (
    <div
      className={cn(
        CARD_CLASS,
        "cursor-grabbing bg-surface shadow-lg ring-1 ring-white/10",
      )}
    >
      <CardBody item={item} />
    </div>
  );
}

export function BoardCard({
  item,
  onOpen,
  onStatusChange,
}: {
  item: IssueItem;
  onOpen: (id: string) => void;
  onStatusChange: (id: string, status: IssueStatus) => void;
}) {
  const { setNodeRef, listeners, attributes, transform, transition, isDragging } =
    useSortable({ id: item.id });

  return (
    <div
      ref={setNodeRef}
      style={{ transform: CSS.Translate.toString(transform), transition }}
      {...attributes}
      {...listeners}
      onClick={() => onOpen(item.id)}
      onKeyDown={(event) => {
        if (event.key === "Enter") {
          event.preventDefault();
          onOpen(item.id);
        }
      }}
      aria-label={`Ouvrir « ${item.title} »`}
      className={cn(
        CARD_CLASS,
        "group cursor-grab text-left transition-colors hover:border-white/[0.16] hover:bg-surface/90 focus-visible:border-white/[0.24] active:cursor-grabbing",
        isDragging && "opacity-0",
      )}
    >
      <CardBody
        item={item}
        menu={
          <DropdownMenu>
            <DropdownMenuTrigger
              aria-label="Déplacer le ticket"
              onPointerDown={(event) => event.stopPropagation()}
              onClick={(event) => event.stopPropagation()}
              className="-mt-1 -mr-1 shrink-0 rounded p-1 text-ink-faint opacity-0 transition-opacity group-hover:opacity-100 hover:text-ink focus-visible:opacity-100 data-[state=open]:opacity-100"
            >
              <MoreHorizontal className="size-3.5" />
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-40">
              <DropdownMenuLabel className="text-2xs font-medium text-ink-faint">
                Déplacer vers
              </DropdownMenuLabel>
              {STATUS_ORDER.filter((status) => status !== item.status).map(
                (status) => (
                  <DropdownMenuItem
                    key={status}
                    onSelect={() => onStatusChange(item.id, status)}
                  >
                    {STATUS_LABEL[status]}
                  </DropdownMenuItem>
                ),
              )}
            </DropdownMenuContent>
          </DropdownMenu>
        }
      />
    </div>
  );
}
