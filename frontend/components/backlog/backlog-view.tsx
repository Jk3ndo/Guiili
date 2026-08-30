"use client";

import { PageShell } from "@/components/shell/page-shell";
import { useBacklog } from "@/lib/api/hooks";
import type { HighlightedFixes } from "@/lib/backlog/highlight";
import { useShell } from "@/lib/shell/shell-context";

import { Board } from "./board";

export function BacklogView({
  highlighted,
}: {
  highlighted: HighlightedFixes;
}) {
  const { workspace } = useShell();
  const { items, version, persistStatus } = useBacklog(workspace);

  return (
    <PageShell
      title="Backlog des correctifs"
      subtitle="Tableau d'ingénierie : chaque anomalie détectée, son correctif et sa progression."
    >
      <Board
        key={`${workspace.id}:${version}`}
        items={items}
        highlighted={highlighted}
        onPersistStatus={persistStatus}
      />
    </PageShell>
  );
}
