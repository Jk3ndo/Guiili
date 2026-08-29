"use client";

import { PageShell } from "@/components/shell/page-shell";
import { getOverview } from "@/lib/mock/overview";
import { useShell } from "@/lib/shell/shell-context";

import { MetricCard } from "./metric-card";
import { OverviewHeader } from "./overview-header";
import { PriorityRecommendation } from "./priority-recommendation";
import { RecentEvents } from "./recent-events";

export function OverviewView() {
  const { workspace } = useShell();
  const data = getOverview(workspace);

  return (
    <PageShell header={<OverviewHeader data={data} />}>
      <section className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
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
