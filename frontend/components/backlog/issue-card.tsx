"use client";

import { ChevronDown } from "lucide-react";
import { useState } from "react";

import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import type { FixToken } from "@/lib/backlog/highlight";
import { relativeDays } from "@/lib/format";
import {
  CATEGORY_LABEL,
  type IssueItem,
  type IssueSeverity,
  type IssueStatus,
} from "@/lib/mock/backlog";
import { cn } from "@/lib/utils";

import { FixBlock } from "./fix-block";
import { StatusSelect } from "./status-select";

const SEVERITY_DOT: Record<IssueSeverity, string> = {
  critical: "bg-danger",
  warning: "bg-warn",
  info: "bg-ink-faint",
};

export function IssueCard({
  item,
  status,
  tokens,
  onStatusChange,
}: {
  item: IssueItem;
  status: IssueStatus;
  tokens?: FixToken[][];
  onStatusChange: (id: string, status: IssueStatus) => void;
}) {
  const [open, setOpen] = useState(false);
  const resolved = status === "done";

  return (
    <div
      className={cn(
        "rounded-xl border border-white/[0.08] bg-surface/60 p-5 backdrop-blur-sm transition-opacity",
        resolved && "opacity-70",
      )}
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex items-start gap-3">
          <span
            className={cn(
              "mt-1.5 size-1.5 shrink-0 rounded-full",
              SEVERITY_DOT[item.severity],
            )}
          />
          <div className="space-y-1">
            <div className="flex flex-wrap items-center gap-2">
              <h3
                className={cn(
                  "text-sm font-medium text-ink",
                  resolved && "line-through decoration-white/25",
                )}
              >
                {item.title}
              </h3>
              <span className="inline-flex h-[18px] items-center rounded border border-hairline bg-white/[0.03] px-1.5 font-mono text-2xs text-ink-muted">
                {CATEGORY_LABEL[item.category]}
              </span>
            </div>
            <p className="max-w-2xl text-xs leading-relaxed text-ink-muted">
              {item.context}
            </p>
          </div>
        </div>

        <StatusSelect
          status={status}
          onChange={(next) => onStatusChange(item.id, next)}
        />
      </div>

      <Collapsible open={open} onOpenChange={setOpen} className="mt-3">
        <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1">
          <CollapsibleTrigger className="inline-flex items-center gap-1.5 text-xs font-medium text-ink-muted transition-colors hover:text-ink">
            <ChevronDown
              className={cn(
                "size-3.5 transition-transform",
                open && "rotate-180",
              )}
            />
            {open ? "Masquer la recommandation" : "Voir la recommandation"}
          </CollapsibleTrigger>
          <span className="text-2xs text-ink-faint">
            Détecté {relativeDays(item.detectedDaysAgo)}
          </span>
        </div>
        <CollapsibleContent>
          <FixBlock fix={item.fix} tokens={tokens} />
        </CollapsibleContent>
      </Collapsible>
    </div>
  );
}
