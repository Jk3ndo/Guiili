"use client";

import { ArrowUpRight, ChevronDown, Search } from "lucide-react";
import { useMemo, useState } from "react";

import { formatCount } from "@/lib/format";
import type { SearchUrl, UrlIndexStatus } from "@/lib/mock/audit";
import { cn } from "@/lib/utils";

const STATUS_DOT: Record<UrlIndexStatus, string> = {
  Indexée: "bg-ok",
  "Exclue noindex": "bg-danger",
  "Redirection 301": "bg-ink-faint",
  "Découverte non indexée": "bg-warn",
};

const STATUS_ORDER: UrlIndexStatus[] = [
  "Indexée",
  "Découverte non indexée",
  "Exclue noindex",
  "Redirection 301",
];

function formatCtr(ctr: number): string {
  return `${ctr.toFixed(1).replace(".", ",")} %`;
}

function UrlRow({ entry }: { entry: SearchUrl }) {
  const [open, setOpen] = useState(false);

  return (
    <>
      <tr
        className={cn(
          "border-t border-white/[0.05] transition-colors hover:bg-white/[0.02]",
          open && "bg-white/[0.02]",
        )}
      >
        <td className="py-2.5 pr-3 pl-4">
          <span className="font-mono text-xs text-ink">{entry.url}</span>
        </td>
        <td className="px-3 py-2.5">
          <span className="flex items-center gap-2 text-xs text-ink-muted">
            <span
              className={cn(
                "size-1.5 shrink-0 rounded-full",
                STATUS_DOT[entry.status],
              )}
            />
            {entry.status}
          </span>
        </td>
        <td className="px-3 py-2.5 text-right font-mono text-xs text-ink-muted tabular-nums">
          {formatCount(entry.clicks)}
        </td>
        <td className="px-3 py-2.5 text-right font-mono text-xs text-ink-muted tabular-nums">
          {formatCount(entry.impressions)}
        </td>
        <td className="px-3 py-2.5 text-right font-mono text-xs text-ink-muted tabular-nums">
          {entry.impressions > 0 ? formatCtr(entry.ctr) : "—"}
        </td>
        <td className="py-2.5 pr-4 pl-3 text-right">
          <button
            type="button"
            onClick={() => setOpen((value) => !value)}
            aria-expanded={open}
            className="inline-flex items-center gap-1 rounded-md border border-white/[0.08] bg-white/[0.03] px-2 py-1 text-2xs font-medium text-ink-muted transition-colors hover:bg-white/[0.06] hover:text-ink"
          >
            Action marketing
            <ChevronDown
              className={cn(
                "size-3 transition-transform",
                open && "rotate-180",
              )}
            />
          </button>
        </td>
      </tr>
      {open && (
        <tr className="border-t border-white/[0.05] bg-white/[0.02]">
          <td colSpan={6} className="px-4 py-3">
            <div className="flex gap-2.5">
              <ArrowUpRight className="mt-0.5 size-3.5 shrink-0 text-ink-faint" />
              <p className="text-xs leading-relaxed text-ink-muted">
                {entry.marketingAction}
              </p>
            </div>
          </td>
        </tr>
      )}
    </>
  );
}

export function UrlExplorerTable({ urls }: { urls: SearchUrl[] }) {
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState<UrlIndexStatus | "all">("all");

  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return urls
      .filter((entry) => (status === "all" ? true : entry.status === status))
      .filter((entry) =>
        needle ? entry.url.toLowerCase().includes(needle) : true,
      )
      .sort(
        (a, b) =>
          STATUS_ORDER.indexOf(a.status) - STATUS_ORDER.indexOf(b.status) ||
          b.impressions - a.impressions,
      );
  }, [urls, query, status]);

  if (urls.length === 0) return null;

  return (
    <section className="space-y-3">
      <div className="space-y-1">
        <h2 className="text-sm font-medium text-ink">
          Explorateur d&apos;URLs
        </h2>
        <p className="text-xs text-ink-faint">
          Échantillon Search Console (30 j) avec l&apos;action marketing
          prioritaire par page.
        </p>
      </div>

      <div className="overflow-hidden rounded-xl border border-white/[0.08] bg-surface/60 backdrop-blur-sm">
        <div className="flex flex-wrap items-center gap-2 border-b border-white/[0.06] p-3">
          <div className="relative min-w-[180px] flex-1">
            <Search className="pointer-events-none absolute top-1/2 left-2.5 size-3.5 -translate-y-1/2 text-ink-faint" />
            <input
              type="text"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Filtrer par URL…"
              className="h-8 w-full rounded-md border border-white/[0.08] bg-white/[0.03] pr-2 pl-8 text-xs text-ink placeholder:text-ink-faint focus:border-white/20 focus:outline-none"
            />
          </div>
          <select
            value={status}
            onChange={(event) =>
              setStatus(event.target.value as UrlIndexStatus | "all")
            }
            className="h-8 rounded-md border border-white/[0.08] bg-white/[0.03] px-2 text-xs text-ink-muted focus:border-white/20 focus:outline-none"
          >
            <option value="all">Tous les statuts</option>
            {STATUS_ORDER.map((value) => (
              <option key={value} value={value}>
                {value}
              </option>
            ))}
          </select>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full min-w-[640px]">
            <thead>
              <tr className="bg-white/[0.02] text-2xs font-medium text-ink-muted">
                <th className="py-2.5 pr-3 pl-4 text-left font-medium">URL</th>
                <th className="px-3 py-2.5 text-left font-medium">
                  Statut d&apos;indexation
                </th>
                <th className="px-3 py-2.5 text-right font-medium">Clics</th>
                <th className="px-3 py-2.5 text-right font-medium">
                  Impressions
                </th>
                <th className="px-3 py-2.5 text-right font-medium">CTR</th>
                <th className="py-2.5 pr-4 pl-3" />
              </tr>
            </thead>
            <tbody>
              {filtered.map((entry) => (
                <UrlRow key={entry.url} entry={entry} />
              ))}
            </tbody>
          </table>
        </div>

        {filtered.length === 0 && (
          <p className="border-t border-white/[0.05] px-4 py-6 text-center text-xs text-ink-faint">
            Aucune URL ne correspond à ce filtre.
          </p>
        )}
      </div>
    </section>
  );
}
