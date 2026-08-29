"use client";

import { PageShell } from "@/components/shell/page-shell";
import type { HighlightedFixes } from "@/lib/backlog/highlight";
import { getBacklog } from "@/lib/mock/backlog";
import { useShell } from "@/lib/shell/shell-context";

import { Backlog } from "./backlog";

export function BacklogView({
  highlighted,
}: {
  highlighted: HighlightedFixes;
}) {
  const { workspace } = useShell();

  return (
    <PageShell
      title="Backlog des correctifs"
      subtitle="Historique des problèmes détectés et suivi de leur résolution dans le temps."
    >
      <Backlog
        key={workspace.id}
        items={getBacklog(workspace)}
        highlighted={highlighted}
      />
    </PageShell>
  );
}
