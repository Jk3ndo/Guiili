"use client";

import { ChevronRight } from "lucide-react";

import type { MeasurementItemDto, MeasurementPlanDto } from "@/lib/api/measurement";

import { reasonLabel, stateLabel } from "./labels";

export function NextActions({
  plan,
  onOpen,
}: {
  plan: MeasurementPlanDto;
  onOpen: (itemId: string) => void;
}) {
  if (plan.last_checked_at === null) return null;

  const byId = new Map(plan.items.map((item) => [item.id, item]));
  const items = plan.next_actions
    .map((id) => byId.get(id))
    .filter((item): item is MeasurementItemDto => item !== undefined);

  if (items.length === 0) {
    return (
      <p className="text-xs text-ink-muted">
        Rien d&apos;urgent : tout ce qui compte est en place. Ouvre « Pour aller plus loin » pour
        approfondir.
      </p>
    );
  }

  return (
    <section className="space-y-2">
      <h2 className="text-sm font-medium text-ink">Tes prochaines actions</h2>
      <ul className="overflow-hidden rounded-xl border border-white/[0.08] bg-surface/30">
        {items.map((item) => (
          <li key={item.id} className="border-t border-white/[0.05] first:border-t-0">
            <button
              type="button"
              onClick={() => onOpen(item.id)}
              className="flex w-full items-center gap-3 px-4 py-3 text-left hover:bg-white/[0.02]"
            >
              <span className="min-w-0 flex-1">
                <span className="block truncate text-sm font-medium text-ink">{item.title}</span>
                <span className="block text-xs leading-relaxed text-ink-muted">
                  {(!item.done && reasonLabel(item.reason)) || item.why}
                </span>
              </span>
              <span className="shrink-0 text-xs text-ink-muted">{stateLabel(item)}</span>
              <ChevronRight className="size-4 shrink-0 text-ink-faint" />
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}
