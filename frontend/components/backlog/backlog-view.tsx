"use client";

import { PageShell } from "@/components/shell/page-shell";
import type { HighlightedFixes } from "@/lib/backlog/highlight";
import { getBacklog } from "@/lib/mock/backlog";
import { useShell } from "@/lib/shell/shell-context";

import { Board } from "./board";

export function BacklogView({
  highlighted,
}: {
  highlighted: HighlightedFixes;
}) {
  const { workspace } = useShell();

  return (
    <PageShell
      title="Backlog des correctifs"
      subtitle="Tableau d'ingénierie : chaque anomalie détectée, son correctif et sa progression."
    >
      <Board
        key={workspace.id}
        items={getBacklog(workspace)}
        highlighted={highlighted}
      />
    </PageShell>
  );
}
