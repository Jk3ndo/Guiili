import {
  FileCode2,
  Package,
  Plug,
  ScanLine,
  type LucideIcon,
} from "lucide-react";

import { relativeHours } from "@/lib/format";
import type { AuditEvent, AuditEventKind } from "@/lib/mock/types";

const KIND_ICON: Record<AuditEventKind, LucideIcon> = {
  scan: ScanLine,
  export: Package,
  snippet: FileCode2,
  connection: Plug,
};

export function RecentEvents({ events }: { events: AuditEvent[] }) {
  return (
    <section>
      <div className="flex items-center justify-between pb-2">
        <h2 className="text-sm font-medium text-ink">Événements récents</h2>
        <a
          href="/backlog"
          className="text-xs text-ink-faint transition-colors hover:text-ink-muted"
        >
          Journal complet
        </a>
      </div>

      <table className="w-full border-t border-hairline text-xs">
        <thead>
          <tr className="border-b border-hairline text-ink-faint">
            <th className="py-1.5 pr-4 text-left font-medium">Action</th>
            <th className="py-1.5 pr-4 text-left font-medium">Cible</th>
            <th className="py-1.5 pr-4 text-left font-medium">État</th>
            <th className="py-1.5 text-right font-medium">Date</th>
          </tr>
        </thead>
        <tbody>
          {events.map((ev) => {
            const Icon = KIND_ICON[ev.kind];
            const ok = ev.result === "success";
            return (
              <tr
                key={ev.id}
                className="border-b border-hairline last:border-0"
              >
                <td className="py-2 pr-4 text-ink">
                  <span className="flex items-center gap-2">
                    <Icon className="size-3.5 shrink-0 text-ink-faint" />
                    {ev.action}
                  </span>
                </td>
                <td className="py-2 pr-4 font-mono text-2xs text-ink-muted">
                  {ev.target}
                </td>
                <td className="py-2 pr-4">
                  <span
                    className={
                      ok
                        ? "text-2xs font-medium text-ok"
                        : "text-2xs font-medium text-danger"
                    }
                  >
                    {ok ? "OK" : "Échec"}
                  </span>
                </td>
                <td className="py-2 text-right text-2xs text-ink-faint">
                  {relativeHours(ev.hoursAgo)}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </section>
  );
}
