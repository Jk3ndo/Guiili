"use client";

import { PageShell } from "@/components/shell/page-shell";
import { useOverview } from "@/lib/api/hooks";
import { useShell } from "@/lib/shell/shell-context";

import { MetricCard } from "./metric-card";
import { OverviewHeader } from "./overview-header";
import { PriorityRecommendation } from "./priority-recommendation";
import { RecentEvents } from "./recent-events";

export function OverviewView() {
  const { workspace } = useShell();
  const { data, rescan } = useOverview(workspace);

  return (
    <PageShell header={<OverviewHeader data={data} onRescan={rescan} />}>
      <section className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {data.metrics.map((metric) => (
          <MetricCard key={metric.id} metric={metric} />
        ))}
      </section>

      {data.recommendation && (
        <PriorityRecommendation reco={data.recommendation} />
      )}

      <RecentEvents events={data.events} />
    </PageShell>
  );
}
