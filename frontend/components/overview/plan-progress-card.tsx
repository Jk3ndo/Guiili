"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import {
  describeMeasurementError,
  fetchMeasurementPlan,
  type MeasurementPlanDto,
} from "@/lib/api/measurement";

const CARD_CLASS =
  "flex flex-wrap items-center justify-between gap-3 rounded-xl border border-white/[0.08] bg-surface/60 p-5 backdrop-blur-sm";

type PlanState =
  | { status: "loading" }
  | { status: "ready"; plan: MeasurementPlanDto }
  | { status: "error"; message: string };

/**
 * Résumé du plan de mesure sur la vue d'ensemble : pourcentage et prochaine action.
 * Réservé aux vrais sites (aucune donnée factice pour un site de démonstration).
 */
export function PlanProgressCard({ websiteId }: { websiteId: string | undefined }) {
  // L'état est rattaché au site : changer de site ne montre jamais le plan du précédent.
  const [state, setState] = useState<PlanState & { websiteId?: string }>({
    status: "loading",
  });

  useEffect(() => {
    if (!websiteId) return;
    let cancelled = false;
    void fetchMeasurementPlan(websiteId)
      .then((plan) => {
        if (!cancelled) setState({ status: "ready", plan, websiteId });
      })
      .catch((error: unknown) => {
        if (!cancelled) {
          setState({ status: "error", message: describeMeasurementError(error), websiteId });
        }
      });
    return () => {
      cancelled = true;
    };
  }, [websiteId]);

  if (!websiteId || state.websiteId !== websiteId) return null;

  if (state.status === "error") {
    return (
      <div className={CARD_CLASS}>
        <div className="space-y-1">
          <p className="text-sm font-medium text-ink">Plan de mesure</p>
          <p className="text-xs text-ink-muted">
            Avancement indisponible pour le moment : {state.message}
          </p>
        </div>
      </div>
    );
  }
  if (state.status !== "ready") return null;

  const { plan } = state;
  const started = plan.last_checked_at !== null;
  const next = plan.items.find((item) => item.id === plan.next_actions[0]);
  return (
    <Link
      href="/plan"
      className={`${CARD_CLASS} transition-colors hover:bg-white/[0.03]`}
    >
      <div className="space-y-1">
        <p className="text-sm font-medium text-ink">Plan de mesure</p>
        <p className="text-xs text-ink-muted">
          {!started
            ? "Découvre ce qu'il faut mettre en place pour mesurer ton trafic et tes conversions."
            : next
              ? `Prochaine action : ${next.title}.`
              : "Tout ce qui compte est en place."}
        </p>
      </div>
      {started && (
        <p className="font-mono text-2xl font-semibold tabular-nums text-ink">
          {plan.overall_percent}%
        </p>
      )}
    </Link>
  );
}
