"use client";

import type { MeasurementPlanDto } from "@/lib/api/measurement";

import { LAYER_LABEL } from "./labels";

export function PlanProgress({ plan }: { plan: MeasurementPlanDto }) {
  return (
    <section className="rounded-xl border border-white/[0.08] bg-surface/60 p-5 backdrop-blur-sm">
      <div className="flex flex-wrap items-baseline justify-between gap-3">
        <div className="space-y-1">
          <p className="text-sm font-medium text-ink">Avancement de ta mesure</p>
          <p className="text-xs text-ink-muted">
            {plan.overall_done} point{plan.overall_done > 1 ? "s" : ""} en place sur{" "}
            {plan.overall_total}
          </p>
        </div>
        <p className="font-mono text-3xl font-semibold tabular-nums text-ink">
          {plan.overall_percent}%
        </p>
      </div>
      <div
        role="progressbar"
        aria-label="Avancement de ta mesure"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={plan.overall_percent}
        className="mt-4 h-1.5 overflow-hidden rounded-full bg-white/[0.06]"
      >
        <div
          className="h-full rounded-full bg-ok transition-all"
          style={{ width: `${plan.overall_percent}%` }}
        />
      </div>
      <ul className="mt-4 grid gap-x-6 gap-y-2 sm:grid-cols-2 lg:grid-cols-5">
        {plan.layers.map((layer) => (
          <li key={layer.layer} className="space-y-1">
            <p className="text-2xs text-ink-faint">
              {LAYER_LABEL[layer.layer] ?? layer.layer}
            </p>
            <p className="font-mono text-xs tabular-nums text-ink-muted">
              {layer.done}/{layer.total}
            </p>
          </li>
        ))}
      </ul>
    </section>
  );
}
