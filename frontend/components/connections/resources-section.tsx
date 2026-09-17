"use client";

import { toast } from "sonner";

import { linkResource, type Ga4PropertyDto, type GscSiteDto, type WebsiteGoogleLinkDto } from "@/lib/api/connections";
import { ApiError } from "@/lib/api/client";

import { ResourceRow } from "./resource-row";

export function ResourcesSection({
  siteName,
  websiteId,
  ga4Properties,
  gscSites,
  links,
  isOwner,
  onChanged,
}: {
  siteName: string;
  websiteId: string | undefined;
  ga4Properties: Ga4PropertyDto[];
  gscSites: GscSiteDto[];
  links: WebsiteGoogleLinkDto[];
  isOwner: boolean;
  onChanged: () => void;
}) {
  async function handleChange(
    type: "ga4_property" | "gsc_site",
    resourceId: string,
    connectionId: string,
    displayName: string,
  ) {
    if (!websiteId) return;
    try {
      await linkResource(websiteId, {
        google_connection_id: connectionId,
        resource_type: type,
        resource_id: resourceId,
        resource_display_name: displayName,
      });
      toast("Ressource réassignée", { description: displayName });
      onChanged();
    } catch (error) {
      toast.error(error instanceof ApiError ? error.message : "Liaison impossible");
    }
  }

  const ga4Link = links.find((l) => l.resource_type === "ga4_property") ?? null;
  const gscLink = links.find((l) => l.resource_type === "gsc_site") ?? null;

  return (
    <section className="space-y-4">
      <div className="space-y-1">
        <h2 className="text-sm font-medium text-ink">
          Ressources assignées à {siteName}
        </h2>
        <p className="max-w-2xl text-xs leading-relaxed text-ink-muted">
          Chaque ressource peut provenir d&apos;un compte Google différent sans
          collision.
        </p>
      </div>

      <div className="space-y-3">
        <ResourceRow
          typeLabel="Google Analytics 4"
          typeNoun="Propriété liée"
          resourceType="ga4_property"
          options={ga4Properties.map((p) => ({
            id: p.resource_id,
            label: p.display_name,
            connectionId: p.source_connection_id,
            sourceEmail: p.source_email,
          }))}
          linked={ga4Link}
          isOwner={isOwner}
          onChange={handleChange}
        />
        <ResourceRow
          typeLabel="Google Search Console"
          typeNoun="Domaine vérifié"
          resourceType="gsc_site"
          options={gscSites.map((s) => ({
            id: s.resource_id,
            label: s.resource_id,
            connectionId: s.source_connection_id,
            sourceEmail: s.source_email,
          }))}
          linked={gscLink}
          isOwner={isOwner}
          onChange={handleChange}
        />
      </div>
    </section>
  );
}
