"use client";

import Link from "next/link";
import { toast } from "sonner";

import type { PriorityRecommendation as Reco } from "@/lib/mock/types";
import { cn } from "@/lib/utils";

export function PriorityRecommendation({ reco }: { reco: Reco }) {
  const isHigh = reco.severity === "high";

  return (
    <div
      className={cn(
        "rounded-xl border border-white/[0.08] bg-surface/60 p-5 backdrop-blur-sm",
        isHigh && "border-l-2 border-l-amber-500/80",
      )}
    >
      <div className="flex items-center gap-2">
        <span
          className={cn(
            "size-1.5 rounded-full",
            isHigh ? "bg-warn" : "bg-ink-faint",
          )}
        />
        <span className="text-sm font-medium text-ink">
          {isHigh ? "Action requise" : "Recommandation"}
        </span>
      </div>

      <h2 className="mt-2.5 text-base leading-relaxed font-medium text-ink">
        {reco.title}
      </h2>
      <p className="mt-1.5 max-w-2xl text-sm leading-relaxed text-ink-muted">
        {reco.detail}
      </p>
      <p className="mt-2.5 text-xs text-ink-faint">
        Impact estimé&nbsp;·&nbsp;{reco.impact}
      </p>

      <button
        type="button"
        onClick={() =>
          toast(
            reco.cta.kind === "gtm"
              ? "Conteneur GTM en cours de génération"
              : "Ouverture du snippet",
            { description: reco.title },
          )
        }
        className="mt-4 inline-flex h-9 items-center gap-2 rounded-lg bg-zinc-100 px-4 text-xs font-medium text-zinc-950 shadow-sm transition-colors hover:bg-zinc-200"
      >
        {reco.cta.label}
      </button>

      <Link
        href="/conseiller"
        className="mt-3 block text-xs text-ink-faint transition-colors hover:text-ink-muted"
      >
        Voir le plan d&apos;action complet →
      </Link>
    </div>
  );
}
