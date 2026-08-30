"use client";

import { toast } from "sonner";

import type { IndexHealth } from "@/lib/mock/audit";

export function IndexHealthBlock({ index }: { index: IndexHealth }) {
  const total = index.valid + index.excluded;
  const pctValid = total === 0 ? 0 : Math.round((index.valid / total) * 100);

  return (
    <section className="grid items-start gap-4 md:grid-cols-2">
      {/* Colonne A — répartition de couverture */}
      <div className="rounded-xl border border-white/[0.08] bg-surface/60 p-5 backdrop-blur-sm">
        <div className="space-y-1 pb-4">
          <h2 className="text-sm font-medium text-ink">Couverture d&apos;indexation</h2>
          <p className="text-xs text-ink-faint">
            <span className="font-mono">{index.property}</span>
          </p>
        </div>

        <div className="flex items-baseline gap-2">
          <span className="font-mono text-3xl font-semibold text-ink tabular-nums">
            {pctValid} %
          </span>
          <span className="text-xs text-ink-faint">des pages indexées</span>
        </div>

        <div className="mt-4 flex h-1.5 overflow-hidden rounded-full bg-white/[0.06]">
          <div className="bg-ok/70" style={{ width: `${pctValid}%` }} />
          <div className="flex-1 bg-warn/40" />
        </div>

        <div className="mt-3 flex justify-between text-xs">
          <span className="text-ink-muted">
            <span className="font-mono text-ink tabular-nums">{index.valid}</span>{" "}
            pages valides
          </span>
          <span className="text-ink-muted">
            <span className="font-mono text-ink tabular-nums">
              {index.excluded}
            </span>{" "}
            pages exclues
          </span>
        </div>
      </div>

      {/* Colonne B — motifs de non-indexation */}
      <div className="rounded-xl border border-white/[0.08] bg-surface/60 p-5 backdrop-blur-sm">
        <div className="space-y-1 pb-2">
          <h2 className="text-sm font-medium text-ink">Motifs de non-indexation</h2>
          <p className="text-xs text-ink-faint">Classés par nombre d&apos;URLs</p>
        </div>

        <ul>
          {index.reasons.map((reason) => (
            <li
              key={reason.label}
              className="flex items-center justify-between gap-3 border-t border-white/[0.05] py-2.5"
            >
              <span className="min-w-0 text-xs text-ink-muted">
                {reason.label}
              </span>
              <span className="flex shrink-0 items-center gap-3">
                <span className="font-mono text-xs text-ink tabular-nums">
                  {reason.urls} URL{reason.urls > 1 ? "s" : ""}
                </span>
                <button
                  type="button"
                  onClick={() =>
                    toast("Inspection d'URL", {
                      description: `${reason.label} — ${reason.urls} URL${
                        reason.urls > 1 ? "s" : ""
                      } à examiner dans Search Console.`,
                    })
                  }
                  className="rounded-md border border-white/[0.08] bg-white/[0.03] px-2 py-1 text-2xs font-medium text-ink-muted transition-colors hover:bg-white/[0.06] hover:text-ink"
                >
                  Inspecter
                </button>
              </span>
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}
