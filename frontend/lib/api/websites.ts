import type { Workspace } from "@/lib/mock/types";

import { apiGet, apiPost } from "./client";
import type { CreateWebsiteDto, WebsiteDto } from "./dto";
import { mapStack } from "./mappers";
import { ensureDevSession, registerWebsite } from "./workspaces";

/** DTO backend d'un site réel -> `Workspace` que le shell sait afficher. */
export function websiteToWorkspace(
  dto: WebsiteDto | CreateWebsiteDto,
): Workspace {
  registerWebsite(dto.domain, dto.id);
  return {
    id: dto.id,
    websiteId: dto.id,
    name: dto.display_name,
    domain: dto.domain,
    stack: mapStack(dto.detected_stack),
    // Aucune identité Google associée à la création : à relier depuis /connections.
    tokenStatus: "needs_reauth",
  };
}

export async function listWebsites(): Promise<Workspace[]> {
  await ensureDevSession();
  const dtos = await apiGet<WebsiteDto[]>("/websites");
  return dtos.map(websiteToWorkspace);
}

export interface CreateWebsiteInput {
  name: string;
  domain: string;
}

export interface CreatedWebsite {
  workspace: Workspace;
  detectedStackLabel: string;
}

const STACK_LABEL: Record<string, string> = {
  nextjs: "Next.js",
  wordpress: "WordPress",
  woocommerce: "WooCommerce",
  nuxt: "Nuxt",
  vue: "Vue",
  angular: "Angular",
  generic: "site générique",
  unknown: "stack non identifiée",
};

export async function createWebsite(
  input: CreateWebsiteInput,
): Promise<CreatedWebsite> {
  await ensureDevSession();
  const dto = await apiPost<CreateWebsiteDto>("/websites", input);
  const stack = dto.detection.stack;
  return {
    workspace: websiteToWorkspace(dto),
    detectedStackLabel: STACK_LABEL[stack] ?? stack,
  };
}
