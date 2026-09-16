import { apiDelete, apiGet, apiPost } from "./client";

export interface ConnectionSummaryDto {
  id: string;
  email: string;
  status: "active" | "needs_reauth" | "revoked";
}

export interface Ga4PropertyDto {
  resource_id: string;
  display_name: string;
  account: string;
  account_display_name: string;
  source_connection_id: string;
  source_email: string;
}

export interface GscSiteDto {
  resource_id: string;
  permission_level: string;
  source_connection_id: string;
  source_email: string;
}

export interface ResourcesResponseDto {
  connections: ConnectionSummaryDto[];
  ga4_properties: Ga4PropertyDto[];
  gtm_containers: unknown[]; // toujours vide (pas de scope GTM), non affiche
  gsc_sites: GscSiteDto[];
}

export function listGoogleResources(): Promise<ResourcesResponseDto> {
  return apiGet<ResourcesResponseDto>("/google/resources");
}

export interface LinkResourceInput {
  google_connection_id: string;
  resource_type: "ga4_property" | "gsc_site";
  resource_id: string;
  resource_display_name?: string | null;
}

export function linkResource(websiteId: string, body: LinkResourceInput): Promise<unknown> {
  return apiPost(`/websites/${websiteId}/link-resource`, body);
}

export function disconnectConnection(connectionId: string): Promise<void> {
  return apiDelete(`/connections/${connectionId}`);
}
