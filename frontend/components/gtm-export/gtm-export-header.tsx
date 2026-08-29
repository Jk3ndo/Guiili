import { StackBadge } from "@/components/shell/stack-badge";
import type { Workspace } from "@/lib/mock/types";

export function GtmExportHeader({ workspace }: { workspace: Workspace }) {
  return (
    <header className="space-y-2 pb-6">
      <div className="flex flex-wrap items-center gap-2.5">
        <h1 className="text-xl font-semibold tracking-tight text-ink">
          Export du conteneur Google Tag Manager
        </h1>
        <StackBadge stack={workspace.stack} />
      </div>
      <p className="max-w-2xl text-sm leading-relaxed text-ink-muted">
        Générez un fichier JSON prêt à l&apos;emploi à importer dans GTM
        (Administration&nbsp;›&nbsp;Importer le conteneur). Zéro accès en écriture
        requis.
      </p>
    </header>
  );
}
