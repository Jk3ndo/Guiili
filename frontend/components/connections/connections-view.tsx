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
  const [status, setStatus] = useState<"loading" | "loaded" | "error">("loading");
  const [error, setError] = useState<string | null>(null);
  const [connections, setConnections] = useState<ConnectionSummaryDto[]>([]);
  const [ga4Properties, setGa4Properties] = useState<Ga4PropertyDto[]>([]);
  const [gscSites, setGscSites] = useState<GscSiteDto[]>([]);
  const [links, setLinks] = useState<WebsiteGoogleLinkDto[]>([]);
  const [isOwner, setIsOwner] = useState(false);

  async function load() {
    setStatus("loading");
    setError(null);
    try {
      const [resources, myWorkspaces] = await Promise.all([
        listGoogleResources(),
        apiGet<WorkspaceMineDto[]>("/workspaces/mine"),
      ]);
      // `/google/resources` agrege les connexions de TOUS les workspaces de
      // l'utilisateur ; cette page n'agit que sur le workspace courant (c'est
      // aussi lui qui determine `isOwner` plus bas). Sans ce filtrage, une
      // connexion d'un autre workspace s'afficherait avec les mauvaises
      // affordances et une re-synchro creerait un doublon dans le mauvais
      // workspace.
      const scopedConnections = resources.connections.filter(
        (c) => c.workspace_id === workspace.realWorkspaceId,
      );
      const scopedConnectionIds = new Set(scopedConnections.map((c) => c.id));
      setConnections(scopedConnections);
      setGa4Properties(
        resources.ga4_properties.filter((p) => scopedConnectionIds.has(p.source_connection_id)),
      );
      setGscSites(
        resources.gsc_sites.filter((s) => scopedConnectionIds.has(s.source_connection_id)),
      );
      setIsOwner(
        myWorkspaces.some((w) => w.id === workspace.realWorkspaceId && w.role === "owner"),
      );
      if (workspace.websiteId) {
        setLinks(await listWebsiteGoogleLinks(workspace.websiteId));
      } else {
        setLinks([]); // sinon on garderait les liaisons du site precedent
      }
      setStatus("loaded");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Erreur inconnue");
      setStatus("error");
    }
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

  if (status === "error") {
    return (
      <PageShell
        title="Connexions Google"
        subtitle="Identités Google reliées et ressources GA4 / Search Console assignées à ce site. Accès en lecture seule."
      >
        <div className="space-y-3">
          <p className="text-xs text-ink-muted">
            Impossible de charger les connexions Google{error ? ` : ${error}` : "."}
          </p>
          <button
            type="button"
            onClick={() => void load()}
            className="inline-flex h-9 items-center rounded-lg border border-white/[0.08] bg-white/[0.03] px-3.5 text-xs font-medium text-ink-muted shadow-sm transition-colors hover:bg-white/[0.06] hover:text-ink"
          >
            Réessayer
          </button>
        </div>
      </PageShell>
    );
  }

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
