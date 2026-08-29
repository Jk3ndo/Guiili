"use client";

import { ArrowRight, Code2, Package, Sparkles, Zap } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import type { PriorityRecommendation as Reco } from "@/lib/mock/types";
import { cn } from "@/lib/utils";

const ACCENT = {
  high: {
    bar: "before:bg-warn",
    wash: "from-warn/[0.06]",
    iconBg: "bg-warn/12 text-warn",
    chip: "bg-warn/10 text-warn ring-warn/20",
  },
  medium: {
    bar: "before:bg-indigo",
    wash: "from-indigo/[0.06]",
    iconBg: "bg-indigo/12 text-indigo",
    chip: "bg-indigo/10 text-indigo ring-indigo/20",
  },
} as const;

export function PriorityRecommendation({ reco }: { reco: Reco }) {
  const a = ACCENT[reco.severity];
  const CtaIcon = reco.cta.kind === "gtm" ? Package : Code2;

  return (
    <div
      className={cn(
        "relative overflow-hidden rounded-lg border border-hairline bg-surface p-5",
        "bg-gradient-to-br to-transparent",
        "before:absolute before:inset-y-0 before:left-0 before:w-0.5",
        a.bar,
        a.wash,
      )}
    >
      <div className="flex gap-4">
        <span
          className={cn(
            "flex size-9 shrink-0 items-center justify-center rounded-lg",
            a.iconBg,
          )}
        >
          <Sparkles className="size-[18px]" />
        </span>

        <div className="min-w-0 flex-1 space-y-2.5">
          <p className="text-2xs font-medium tracking-wider text-ink-faint uppercase">
            Recommandation prioritaire de l&apos;agent
          </p>
          <h2 className="text-base leading-snug font-medium text-ink">
            {reco.title}
          </h2>
          <p className="max-w-2xl text-sm leading-relaxed text-ink-muted">
            {reco.detail}
          </p>

          <div className="flex flex-wrap items-center gap-3 pt-1">
            <span
              className={cn(
                "inline-flex items-center gap-1.5 rounded-md px-2 py-1 text-xs font-medium ring-1 ring-inset",
                a.chip,
              )}
            >
              <Zap className="size-3" />
              {reco.impact}
            </span>
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
              <CtaIcon className="size-3.5" />
              {reco.cta.label}
              <ArrowRight className="size-3.5 opacity-60" />
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}
