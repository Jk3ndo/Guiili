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
      <div className="flex items-center justify-between pb-3">
        <h2 className="text-sm font-medium text-ink">Événements récents</h2>
        <a
          href="/backlog"
          className="text-xs text-ink-faint transition-colors hover:text-ink-muted"
        >
          Journal complet
        </a>
      </div>

      <div className="overflow-hidden rounded-xl border border-white/[0.08] bg-surface/30">
        <table className="w-full text-sm">
          <thead>
            <tr className="bg-white/[0.02] text-xs font-medium text-ink-muted">
              <th className="px-4 py-3 text-left">Action</th>
              <th className="px-4 py-3 text-left">Cible</th>
              <th className="px-4 py-3 text-left">État</th>
              <th className="px-4 py-3 text-right">Date</th>
            </tr>
          </thead>
          <tbody>
            {events.map((ev) => {
              const Icon = KIND_ICON[ev.kind];
              const ok = ev.result === "success";
              return (
                <tr
                  key={ev.id}
                  className="border-t border-white/[0.05] transition-colors hover:bg-white/[0.02]"
                >
                  <td className="px-4 py-3 text-ink">
                    <span className="flex items-center gap-2.5">
                      <Icon className="size-4 shrink-0 text-ink-faint" />
                      {ev.action}
                    </span>
                  </td>
                  <td className="px-4 py-3 font-mono text-xs text-ink-muted">
                    {ev.target}
                  </td>
                  <td className="px-4 py-3">
                    <span
                      className={
                        ok
                          ? "text-xs font-medium text-ok"
                          : "text-xs font-medium text-danger"
                      }
                    >
                      {ok ? "OK" : "Échec"}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-right text-xs text-ink-faint">
                    {relativeHours(ev.hoursAgo)}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}
