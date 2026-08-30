import type { AuditPeriod } from "@/lib/mock/audit";

import { PeriodSelector } from "./period-selector";

export function AuditHeader({
  period,
  onPeriodChange,
}: {
  period: AuditPeriod;
  onPeriodChange: (period: AuditPeriod) => void;
}) {
  return (
    <header className="flex flex-wrap items-start justify-between gap-3 pb-2">
      <div className="space-y-1.5">
        <h1 className="text-xl font-semibold tracking-tight text-ink">
          Audit &amp; Télémétrie de performance
        </h1>
        <p className="max-w-2xl text-sm leading-relaxed text-ink-muted">
          Détail de santé des flux GA4, de l&apos;indexation Search Console et des
          signaux Core Web Vitals.
        </p>
      </div>
      <PeriodSelector value={period} onChange={onPeriodChange} />
    </header>
  );
}
