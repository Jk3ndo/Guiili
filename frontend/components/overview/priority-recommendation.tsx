"use client";

import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import type { PriorityRecommendation as Reco } from "@/lib/mock/types";
import { cn } from "@/lib/utils";

export function PriorityRecommendation({ reco }: { reco: Reco }) {
  const isHigh = reco.severity === "high";

  return (
    <div className="rounded-lg border border-hairline bg-surface p-4">
      <div className="flex items-center gap-2 pb-2.5">
        <span
          className={cn(
            "size-1.5 rounded-full",
            isHigh ? "bg-warn" : "bg-ink-faint",
          )}
        />
        <span className="text-xs font-medium text-ink">
          {isHigh ? "Action requise" : "Recommandation"}
        </span>
      </div>

      <h2 className="text-sm leading-snug font-medium text-ink">{reco.title}</h2>
      <p className="mt-1.5 max-w-2xl text-xs leading-relaxed text-ink-muted">
        {reco.detail}
      </p>
      <p className="mt-2 text-2xs text-ink-faint">
        Impact estimé&nbsp;·&nbsp;{reco.impact}
      </p>

      <div className="mt-3.5">
        <Button
          size="sm"
          onClick={() =>
            toast(
              reco.cta.kind === "gtm"
                ? "Conteneur GTM en cours de génération"
                : "Ouverture du snippet",
              { description: reco.title },
            )
          }
        >
          {reco.cta.label}
        </Button>
      </div>
    </div>
  );
}
