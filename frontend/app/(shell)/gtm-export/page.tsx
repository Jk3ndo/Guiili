import type { Metadata } from "next";

import { PageShell } from "@/components/shell/page-shell";
import { CardGridSkeleton } from "@/components/shell/skeletons";
import { Skeleton } from "@/components/ui/skeleton";

export const metadata: Metadata = { title: "Export GTM & Snippets" };

export default function GtmExportPage() {
  return (
    <PageShell
      title="Export GTM & Snippets"
      subtitle="Conteneur GTM à importer et snippets dataLayer générés pour votre stack."
    >
      <div className="rounded-lg border border-hairline bg-surface p-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="space-y-1.5">
            <Skeleton className="h-3.5 w-48" />
            <Skeleton className="h-3 w-64" />
          </div>
          <Skeleton className="h-8 w-44" />
        </div>
      </div>
      <CardGridSkeleton count={4} height="h-[150px]" />
    </PageShell>
  );
}
