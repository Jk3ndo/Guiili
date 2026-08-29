import type { Metadata } from "next";

import { PageShell } from "@/components/shell/page-shell";
import { CardGridSkeleton } from "@/components/shell/skeletons";
import { Button } from "@/components/ui/button";

export const metadata: Metadata = { title: "Connexions Google" };

export default function ConnectionsPage() {
  return (
    <PageShell
      title="Connexions Google"
      subtitle="Comptes Google liés et propriétés GA4 / Search Console / GTM associées à ce site."
      actions={
        <Button size="sm" variant="outline" disabled>
          Lier un compte Google
        </Button>
      }
    >
      <CardGridSkeleton count={3} height="h-[148px]" />
    </PageShell>
  );
}
