"use client";

import { ChevronDown } from "lucide-react";
import { useState } from "react";

import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import { IMPORT_STEPS } from "@/lib/mock/gtm-export";
import { cn } from "@/lib/utils";

export function ImportGuide() {
  const [open, setOpen] = useState(false);

  return (
    <Collapsible
      open={open}
      onOpenChange={setOpen}
      className="rounded-xl border border-white/[0.08] bg-surface/40"
    >
      <CollapsibleTrigger className="flex w-full items-center justify-between gap-3 px-4 py-3 text-left">
        <span className="text-sm font-medium text-ink">
          Procédure d&apos;importation dans GTM (4 étapes)
        </span>
        <ChevronDown
          className={cn(
            "size-4 shrink-0 text-ink-faint transition-transform",
            open && "rotate-180",
          )}
        />
      </CollapsibleTrigger>
      <CollapsibleContent>
        <ol className="border-t border-white/[0.06] px-4 py-1.5">
          {IMPORT_STEPS.map((step, i) => (
            <li
              key={step.title}
              className="flex gap-3 border-b border-white/[0.05] py-3 last:border-b-0"
            >
              <span className="mt-px flex size-5 shrink-0 items-center justify-center rounded-full border border-white/[0.12] font-mono text-2xs text-ink-muted tabular-nums">
                {i + 1}
              </span>
              <div className="space-y-1">
                <p className="text-sm font-medium text-ink">{step.title}</p>
                <p className="text-xs leading-relaxed text-ink-muted">
                  {step.detail}
                </p>
              </div>
            </li>
          ))}
        </ol>
      </CollapsibleContent>
    </Collapsible>
  );
}
