"use client";

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

export function BoardCard({
  item,
  onOpen,
  onStatusChange,
}: {
  item: IssueItem;
  onOpen: (id: string) => void;
  onStatusChange: (id: string, status: IssueStatus) => void;
}) {
  const resolved = item.status === "done";
  const hasSnippet = Boolean(item.fix.code);

  return (
    <div className="group relative rounded-lg border border-white/[0.08] bg-surface/60 transition-colors hover:border-white/[0.16] hover:bg-surface/90 has-[button:focus-visible]:border-white/[0.24]">
      {/* Full-card click target — a real button, so it is keyboard-reachable. */}
      <button
        type="button"
        onClick={() => onOpen(item.id)}
        aria-label={`Ouvrir « ${item.title} »`}
        className="absolute inset-0 z-0 rounded-lg outline-none"
      />

      <div className="pointer-events-none relative z-10 p-3">
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

          <DropdownMenu>
            <DropdownMenuTrigger
              aria-label="Déplacer le ticket"
              className="pointer-events-auto -mt-1 -mr-1 shrink-0 rounded p-1 text-ink-faint opacity-0 transition-opacity group-hover:opacity-100 hover:text-ink focus-visible:opacity-100 data-[state=open]:opacity-100"
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
        </div>

        <div className="mt-2 flex flex-wrap items-center gap-x-2 gap-y-1 pl-3.5">
          <span className="inline-flex h-[18px] items-center rounded border border-hairline bg-white/[0.03] px-1.5 font-mono text-2xs text-ink-muted">
            {CATEGORY_LABEL[item.category]}
          </span>
          {hasSnippet && (
            <span className="inline-flex items-center gap-1 text-2xs text-ink-faint">
              <Code2 className="size-3" />
              Snippet disponible
            </span>
          )}
        </div>
      </div>
    </div>
  );
}
