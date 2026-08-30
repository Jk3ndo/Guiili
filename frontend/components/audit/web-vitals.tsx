import type { VitalRating, WebVital } from "@/lib/mock/audit";
import { cn } from "@/lib/utils";

import { VitalGauge } from "./vital-gauge";

const RATING_LABEL: Record<VitalRating, string> = {
  good: "Bon",
  warn: "À améliorer",
  bad: "Médiocre",
};

const RATING_DOT: Record<VitalRating, string> = {
  good: "bg-ok",
  warn: "bg-warn",
  bad: "bg-danger",
};

const RATING_TEXT: Record<VitalRating, string> = {
  good: "text-ok",
  warn: "text-warn",
  bad: "text-danger",
};

function VitalCard({ vital }: { vital: WebVital }) {
  return (
    <div className="rounded-xl border border-white/[0.08] bg-surface/60 p-5 backdrop-blur-sm">
      <div className="flex items-center justify-between gap-2">
        <span className="font-mono text-xs font-medium text-ink-muted">
          {vital.id.toUpperCase()}
        </span>
        <span
          className={cn(
            "flex items-center gap-1.5 text-2xs font-medium",
            RATING_TEXT[vital.rating],
          )}
        >
          <span
            className={cn("size-1.5 rounded-full", RATING_DOT[vital.rating])}
          />
          {RATING_LABEL[vital.rating]}
        </span>
      </div>

      <p className="mt-1 text-2xs text-ink-faint">{vital.label}</p>

      <div className="mt-3">
        <span className="font-mono text-3xl font-semibold text-ink tabular-nums">
          {vital.value}
        </span>
        <p className="mt-0.5 text-2xs text-ink-faint">cible {vital.target}</p>
      </div>

      <VitalGauge vital={vital} className="mt-4" />

      <p className="mt-2.5 text-2xs leading-relaxed text-ink-muted">
        {vital.hint}
      </p>
    </div>
  );
}

export function WebVitals({ vitals }: { vitals: WebVital[] }) {
  return (
    <section className="space-y-3">
      <h2 className="text-sm font-medium text-ink">
        Core Web Vitals · terrain (28 j glissants)
      </h2>
      <div className="grid gap-4 sm:grid-cols-3">
        {vitals.map((vital) => (
          <VitalCard key={vital.id} vital={vital} />
        ))}
      </div>
    </section>
  );
}
