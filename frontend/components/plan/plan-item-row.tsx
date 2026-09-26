"use client";

import { ChevronRight } from "lucide-react";

import type { MeasurementItemDto } from "@/lib/api/measurement";
import { cn } from "@/lib/utils";

import { reasonLabel, stateDotClass, stateLabel } from "./labels";

export function PlanItemRow({
  item,
  onOpen,
  selectable,
  selected,
  onToggle,
}: {
  item: MeasurementItemDto;
  onOpen: () => void;
  selectable: boolean;
  selected: boolean;
  onToggle: () => void;
}) {
  const muted = item.state === "dismissed";
  return (
    <div
      className={cn(
        "flex items-center gap-3 border-t border-white/[0.05] px-4 py-3 first:border-t-0 hover:bg-white/[0.02]",
        muted && "opacity-50",
      )}
    >
      {selectable && (
        <input
          type="checkbox"
          checked={selected}
          onChange={onToggle}
          aria-label={`Inclure « ${item.title} » dans mon conteneur GTM`}
          className="size-3.5 shrink-0 accent-zinc-200"
        />
      )}
      <button
        type="button"
        onClick={onOpen}
        className="flex min-w-0 flex-1 items-center gap-3 text-left"
      >
        <span className={cn("size-1.5 shrink-0 rounded-full", stateDotClass(item))} />
        <span className="min-w-0 flex-1">
          <span className="block truncate text-sm font-medium text-ink">
            {item.title}
            {item.quick_win && !item.done && (
              <span className="ml-2 rounded border border-hairline px-1.5 py-0.5 text-2xs font-normal text-ink-muted">
                Gain rapide
              </span>
            )}
          </span>
          <span className="block truncate text-xs text-ink-muted">
            {(!item.done && reasonLabel(item.reason)) || item.why}
          </span>
        </span>
        <span className="shrink-0 text-xs text-ink-muted">{stateLabel(item)}</span>
        <ChevronRight className="size-4 shrink-0 text-ink-faint" />
      </button>
    </div>
  );
}
