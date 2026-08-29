"use client";

import { PageShell } from "@/components/shell/page-shell";
import type { HighlightedSnippets } from "@/lib/mock/gtm-export";
import { useShell } from "@/lib/shell/shell-context";

import { ContainerExport } from "./container-export";
import { GtmExportHeader } from "./gtm-export-header";
import { SnippetLibrary } from "./snippet-library";

export function GtmExportView({
  highlighted,
}: {
  highlighted: HighlightedSnippets;
}) {
  const { workspace } = useShell();

  return (
    <PageShell header={<GtmExportHeader workspace={workspace} />}>
      <ContainerExport workspace={workspace} />
      <SnippetLibrary
        key={workspace.id}
        workspace={workspace}
        highlighted={highlighted}
      />
    </PageShell>
  );
}
