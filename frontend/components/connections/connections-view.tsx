"use client";

import { useEffect, useState } from "react";

import { PageShell } from "@/components/shell/page-shell";
import {
  listGoogleResources,
  listWebsiteGoogleLinks,
  type ConnectionSummaryDto,
  type Ga4PropertyDto,
  type GscSiteDto,
  type WebsiteGoogleLinkDto,
} from "@/lib/api/connections";
import { apiGet } from "@/lib/api/client";
import { useShell } from "@/lib/shell/shell-context";

import { IdentitiesSection } from "./identities-section";
import { ResourcesSection } from "./resources-section";

interface WorkspaceMineDto {
  id: string;
  name: string;
  role: string;
}

export function ConnectionsView() {
  const { workspace } = useShell();
  const [status, setStatus] = useState<"loading" | "loaded">("loading");
  const [connections, setConnections] = useState<ConnectionSummaryDto[]>([]);
  const [ga4Properties, setGa4Properties] = useState<Ga4PropertyDto[]>([]);
  const [gscSites, setGscSites] = useState<GscSiteDto[]>([]);
  const [links, setLinks] = useState<WebsiteGoogleLinkDto[]>([]);
  const [isOwner, setIsOwner] = useState(false);

  async function load() {
    setStatus("loading");
    const [resources, myWorkspaces] = await Promise.all([
      listGoogleResources(),
      apiGet<WorkspaceMineDto[]>("/workspaces/mine"),
    ]);
    setConnections(resources.connections);
    setGa4Properties(resources.ga4_properties);
    setGscSites(resources.gsc_sites);
    setIsOwner(
      myWorkspaces.some((w) => w.id === workspace.realWorkspaceId && w.role === "owner"),
    );
    if (workspace.websiteId) {
      setLinks(await listWebsiteGoogleLinks(workspace.websiteId));
    }
    setStatus("loaded");
  }

  useEffect(() => {
    // `load` resets `status` to "loading" synchronously before its first
    // `await` (so switching workspace hides stale data) — the same
    // fetch-on-mount idiom already exempted for lib/api/hooks.ts.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [workspace.realWorkspaceId, workspace.websiteId]);

  if (status === "loading") return null;

  return (
    <PageShell
      title="Connexions Google"
      subtitle="Identités Google reliées et ressources GA4 / Search Console assignées à ce site. Accès en lecture seule."
    >
      <IdentitiesSection
        connections={connections}
        isOwner={isOwner}
        workspaceId={workspace.realWorkspaceId}
        onChanged={load}
      />
      <ResourcesSection
        key={workspace.id}
        siteName={workspace.name}
        websiteId={workspace.websiteId}
        ga4Properties={ga4Properties}
        gscSites={gscSites}
        links={links}
        isOwner={isOwner}
        onChanged={load}
      />
    </PageShell>
  );
}
