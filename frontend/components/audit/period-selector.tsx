"use client";

import { AUDIT_PERIODS, type AuditPeriod } from "@/lib/mock/audit";
import { cn } from "@/lib/utils";

export function PeriodSelector({
  value,
  onChange,
}: {
  value: AuditPeriod;
  onChange: (period: AuditPeriod) => void;
}) {
  return (
    <div className="inline-flex items-center gap-0.5 rounded-lg border border-white/[0.08] bg-white/[0.03] p-0.5">
      {AUDIT_PERIODS.map((period) => (
        <button
          key={period.id}
          type="button"
          onClick={() => onChange(period.id)}
          className={cn(
            "rounded-md px-2.5 py-1 text-xs font-medium transition-colors",
            value === period.id
              ? "bg-white/[0.08] text-ink"
              : "text-ink-muted hover:text-ink",
          )}
        >
          {period.label}
        </button>
      ))}
    </div>
  );
}
