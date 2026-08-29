"use client";

import { PageShell } from "@/components/shell/page-shell";
import { getConnections } from "@/lib/mock/connections";
import { useShell } from "@/lib/shell/shell-context";

import { IdentitiesSection } from "./identities-section";
import { ResourcesSection } from "./resources-section";

export function ConnectionsView() {
  const { workspace } = useShell();
  const data = getConnections(workspace);

  return (
    <PageShell
      title="Connexions Google"
      subtitle="Identités Google reliées et ressources GA4 / GTM / Search Console assignées à ce site. Accès en lecture seule."
    >
      <IdentitiesSection identities={data.identities} />
      <ResourcesSection
        key={workspace.id}
        siteName={workspace.name}
        resources={data.resources}
      />
    </PageShell>
  );
}
