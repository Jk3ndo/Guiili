import {
  Check,
  FileCode2,
  Package,
  Plug,
  ScanLine,
  X,
  type LucideIcon,
} from "lucide-react";

import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { relativeHours } from "@/lib/format";
import type { AuditEvent, AuditEventKind } from "@/lib/mock/types";
import { cn } from "@/lib/utils";

const KIND_ICON: Record<AuditEventKind, LucideIcon> = {
  scan: ScanLine,
  export: Package,
  snippet: FileCode2,
  connection: Plug,
};

export function RecentEvents({ events }: { events: AuditEvent[] }) {
  return (
    <div className="rounded-lg border border-hairline bg-surface">
      <div className="flex items-center justify-between px-4 py-3">
        <h2 className="text-sm font-medium text-ink">
          Derniers événements &amp; correctifs
        </h2>
        <a
          href="/backlog"
          className="text-xs text-ink-faint transition-colors hover:text-ink-muted"
        >
          Tout le journal
        </a>
      </div>
      <Table>
        <TableHeader>
          <TableRow className="border-hairline hover:bg-transparent">
            <TableHead className="h-8 px-4 text-2xs font-medium text-ink-faint">
              Action
            </TableHead>
            <TableHead className="h-8 text-2xs font-medium text-ink-faint">
              Cible
            </TableHead>
            <TableHead className="h-8 text-2xs font-medium text-ink-faint">
              Résultat
            </TableHead>
            <TableHead className="h-8 px-4 text-right text-2xs font-medium text-ink-faint">
              Quand
            </TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {events.map((ev) => {
            const Icon = KIND_ICON[ev.kind];
            const ok = ev.result === "success";
            return (
              <TableRow key={ev.id} className="border-hairline">
                <TableCell className="px-4 py-2.5">
                  <span className="flex items-center gap-2.5 text-xs text-ink">
                    <Icon className="size-3.5 shrink-0 text-ink-faint" />
                    {ev.action}
                  </span>
                </TableCell>
                <TableCell className="py-2.5 font-mono text-2xs text-ink-muted">
                  {ev.target}
                </TableCell>
                <TableCell className="py-2.5">
                  <span
                    className={cn(
                      "inline-flex items-center gap-1 rounded-full px-1.5 py-0.5 text-2xs font-medium ring-1 ring-inset",
                      ok
                        ? "bg-ok/[0.08] text-ok ring-ok/20"
                        : "bg-danger/[0.08] text-danger ring-danger/20",
                    )}
                  >
                    {ok ? (
                      <Check className="size-2.5" />
                    ) : (
                      <X className="size-2.5" />
                    )}
                    {ok ? "Succès" : "Échec"}
                  </span>
                </TableCell>
                <TableCell className="px-4 py-2.5 text-right text-2xs text-ink-faint">
                  {relativeHours(ev.hoursAgo)}
                </TableCell>
              </TableRow>
            );
          })}
        </TableBody>
      </Table>
    </div>
  );
}
