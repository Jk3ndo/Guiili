"use client";

import { ExternalLink, RefreshCw } from "lucide-react";

import { StackBadge } from "@/components/shell/stack-badge";
import { relativeHours } from "@/lib/format";
import type { OverviewData, StackId } from "@/lib/mock/types";

export function OverviewHeader({
  data,
  stack,
  stackLabel,
  onRescan,
}: {
  data: OverviewData;
  /** Stack identity from the shell workspace — same source as the sidebar. */
  stack: StackId;
  stackLabel?: string | null;
  onRescan?: () => void | Promise<void>;
}) {
  return (
    <header className="flex flex-wrap items-start justify-between gap-3 pb-6">
      <div className="space-y-1.5">
        <div className="flex items-center gap-2.5">
          <h1 className="text-xl font-semibold tracking-tight text-ink">
            {data.siteName}
          </h1>
          <StackBadge stack={stack} label={stackLabel} />
        </div>
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-sm text-ink-muted">
          <a
            href={`https://${data.domain}`}
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-1 transition-colors hover:text-ink"
          >
            {data.domain}
            <ExternalLink className="size-3.5" />
          </a>
          <span className="text-ink-faint">·</span>
          <span>Dernier scan {relativeHours(data.lastScanHoursAgo)}</span>
        </div>
      </div>

      <button
        type="button"
        onClick={() => void onRescan?.()}
        className="inline-flex h-9 items-center gap-2 rounded-lg border border-white/[0.08] bg-white/[0.03] px-3.5 text-xs font-medium text-ink-muted shadow-sm transition-colors hover:bg-white/[0.06] hover:text-ink"
      >
        <RefreshCw className="size-3.5" />
        Re-scanner
      </button>
    </header>
  );
}
