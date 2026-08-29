"use client";

import { ExternalLink, RefreshCw } from "lucide-react";
import { toast } from "sonner";

import { StackBadge } from "@/components/shell/stack-badge";
import { Button } from "@/components/ui/button";
import { relativeHours } from "@/lib/format";
import type { OverviewData } from "@/lib/mock/types";

export function OverviewHeader({ data }: { data: OverviewData }) {
  return (
    <header className="flex flex-wrap items-start justify-between gap-3 pb-5">
      <div className="space-y-1.5">
        <div className="flex items-center gap-2">
          <h1 className="text-lg font-semibold tracking-tight text-ink">
            {data.siteName}
          </h1>
          <StackBadge stack={data.stack} />
        </div>
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-ink-muted">
          <a
            href={`https://${data.domain}`}
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-1 text-ink-faint transition-colors hover:text-ink"
          >
            {data.domain}
            <ExternalLink className="size-3" />
          </a>
          <span className="text-ink-faint">·</span>
          <span>Dernier scan {relativeHours(data.lastScanHoursAgo)}</span>
        </div>
      </div>

      <Button
        size="sm"
        variant="outline"
        onClick={() =>
          toast("Re-scan lancé", {
            description: `Analyse de ${data.domain} en file d'attente.`,
          })
        }
      >
        <RefreshCw className="size-3.5" />
        Re-scanner
      </Button>
    </header>
  );
}
