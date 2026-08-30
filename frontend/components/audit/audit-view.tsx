"use client";

import { useState } from "react";

import { PageShell } from "@/components/shell/page-shell";
import { getAudit, periodLabel, type AuditPeriod } from "@/lib/mock/audit";
import { useShell } from "@/lib/shell/shell-context";

import { AuditHeader } from "./audit-header";
import { Ga4Observability } from "./ga4-observability";
import { IndexHealthBlock } from "./index-health";
import { WebVitals } from "./web-vitals";

export function AuditView() {
  const { workspace } = useShell();
  const [period, setPeriod] = useState<AuditPeriod>("7d");
  const data = getAudit(workspace, period);

  return (
    <PageShell
      header={<AuditHeader period={period} onPeriodChange={setPeriod} />}
      className="space-y-8"
    >
      <Ga4Observability stream={data.ga4} periodLabel={periodLabel(period)} />
      <IndexHealthBlock index={data.index} />
      <WebVitals vitals={data.vitals} />
    </PageShell>
  );
}
