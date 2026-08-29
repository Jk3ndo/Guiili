import type { Metadata } from "next";

import { PageShell } from "@/components/shell/page-shell";
import {
  ChartSkeleton,
  DonutSkeleton,
  KpiRowSkeleton,
} from "@/components/shell/skeletons";

export const metadata: Metadata = { title: "Vue d'ensemble" };

export default function OverviewPage() {
  return (
    <PageShell
      title="Vue d'ensemble"
      subtitle="Santé SEO, trafic et Core Web Vitals du site suivi, en un coup d'œil."
    >
      <KpiRowSkeleton />
      <div className="grid items-start gap-4 xl:grid-cols-[1.6fr_1fr]">
        <ChartSkeleton label="30 derniers jours" />
        <DonutSkeleton label="Répartition des correctifs par sévérité" />
      </div>
    </PageShell>
  );
}
