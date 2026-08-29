import type { Metadata } from "next";

import { PageShell } from "@/components/shell/page-shell";
import { ChartSkeleton, TableSkeleton } from "@/components/shell/skeletons";

export const metadata: Metadata = { title: "Audit & Métriques" };

export default function AuditPage() {
  return (
    <PageShell
      title="Audit & Métriques"
      subtitle="Résultats détaillés du dernier diagnostic : PageSpeed, Search Console, GA4."
    >
      <ChartSkeleton label="Score de performance dans le temps" />
      <TableSkeleton rows={8} />
    </PageShell>
  );
}
