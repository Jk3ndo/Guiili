import { formatCount } from "@/lib/format";
import type { EventConformity, Ga4Stream } from "@/lib/mock/audit";
import { cn } from "@/lib/utils";

const CONFORMITY_DOT: Record<EventConformity, string> = {
  conforme: "bg-ok",
  partial: "bg-warn",
  missing: "bg-danger",
};

const CONFORMITY_TEXT: Record<EventConformity, string> = {
  conforme: "text-ink-muted",
  partial: "text-warn",
  missing: "text-danger",
};

export function Ga4Observability({
  stream,
  periodLabel,
}: {
  stream: Ga4Stream;
  periodLabel: string;
}) {
  return (
    <section className="rounded-xl border border-white/[0.08] bg-surface/60 p-5 backdrop-blur-sm">
      <div className="flex flex-wrap items-start justify-between gap-3 pb-4">
        <div className="space-y-1">
          <h2 className="text-sm font-medium text-ink">Observabilité GA4</h2>
          <p className="text-xs text-ink-faint">
            Flux &amp; qualité des données ·{" "}
            <span className="font-mono">{stream.property}</span>
          </p>
        </div>
        <span className="inline-flex items-center gap-1.5 rounded-md border border-white/[0.08] bg-white/[0.02] px-2 py-1 text-2xs font-medium text-ink-muted">
          <span className="size-1.5 rounded-full bg-ok" />
          {stream.statusLine}
        </span>
      </div>

      <div className="overflow-hidden rounded-xl border border-white/[0.08] bg-surface/30">
        <table className="w-full text-sm">
          <thead>
            <tr className="bg-white/[0.02] text-2xs font-medium text-ink-muted">
              <th className="px-4 py-2.5 text-left font-medium">Événement</th>
              <th className="px-4 py-2.5 text-left font-medium">Validation des paramètres</th>
              <th className="px-4 py-2.5 text-right font-medium">
                Volume · {periodLabel}
              </th>
            </tr>
          </thead>
          <tbody>
            {stream.events.map((event) => (
              <tr
                key={event.name}
                className="border-t border-white/[0.05] transition-colors hover:bg-white/[0.02]"
              >
                <td className="px-4 py-2.5 font-mono text-xs text-ink">
                  {event.name}
                </td>
                <td className="px-4 py-2.5">
                  <span className="flex items-center gap-2">
                    <span
                      className={cn(
                        "size-1.5 shrink-0 rounded-full",
                        CONFORMITY_DOT[event.conformity],
                      )}
                    />
                    <span
                      className={cn("text-xs", CONFORMITY_TEXT[event.conformity])}
                    >
                      {event.note}
                    </span>
                  </span>
                </td>
                <td className="px-4 py-2.5 text-right font-mono text-xs text-ink-muted tabular-nums">
                  {formatCount(event.volume)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
