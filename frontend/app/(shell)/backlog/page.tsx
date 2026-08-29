import type { Metadata } from "next";

import { PageShell } from "@/components/shell/page-shell";
import { BoardSkeleton } from "@/components/shell/skeletons";

export const metadata: Metadata = { title: "Backlog Correctifs" };

export default function BacklogPage() {
  return (
    <PageShell
      title="Backlog Correctifs"
      subtitle="Suivi des correctifs détectés : à faire, en cours, corrigés."
    >
      <BoardSkeleton />
    </PageShell>
  );
}
