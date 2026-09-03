import type { SslStatus, Workspace } from "@/lib/mock/types";

import { apiDelete, apiGet, apiPatch, apiPost } from "./client";
import type {
  CreateWebsiteDto,
  RedetectDto,
  SslDto,
  StackGuessDto,
  StackHintDto,
  WebsiteDto,
} from "./dto";
import { mapStack } from "./mappers";
import { ensureDevSession, registerWebsite } from "./workspaces";

const STACK_LABEL: Record<string, string> = {
  nextjs: "Next.js",
  wordpress: "WordPress",
  woocommerce: "WooCommerce",
  nuxt: "Nuxt",
  vue: "Vue",
  angular: "Angular",
  react: "React",
  vite: "Vite",
  php: "PHP",
  generic: "site générique",
  unknown: "stack non identifiée",
};

export function stackLabelOf(stack: string): string {
  return STACK_LABEL[stack] ?? stack;
}

/** Liste des stacks courantes proposées dans le sélecteur « choisir ma stack ». */
export const STACK_PRESETS: string[] = [
  "Next.js",
  "React (CRA / Vite)",
  "Vue",
  "Nuxt",
  "Angular",
  "Svelte / SvelteKit",
  "Astro",
  "Remix",
  "WordPress",
  "WooCommerce",
  "PHP (Symfony)",
  "PHP (Laravel)",
  "PHP (Twig / maison)",
  "Rails",
  "Django",
  "Laravel",
  "ASP.NET",
  "Site statique / HTML",
];

/** DTO backend d'un site réel -> `Workspace` que le shell sait afficher. */
export function websiteToWorkspace(
  dto: WebsiteDto | CreateWebsiteDto,
): Workspace {
  registerWebsite(dto.domain, dto.id);
  const sslStatus = "ssl" in dto ? dto.ssl.status : dto.ssl_status;
  const sslExpiresAt = "ssl" in dto ? dto.ssl.expires_at : dto.ssl_expires_at;
  return {
    id: dto.id,
    websiteId: dto.id,
    name: dto.display_name,
    domain: dto.domain,
    stack: mapStack(dto.detected_stack),
    stackLabel: dto.stack_label,
    sslStatus: (sslStatus ?? null) as SslStatus | null,
    sslExpiresAt: sslExpiresAt ?? null,
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
  allow_insecure?: boolean;
}

export interface CreatedWebsite {
  workspace: Workspace;
  detectedStackLabel: string;
  candidates: StackGuessDto[];
  /** "ssl_verification_failed" quand la stack n'a pas pu être sondée (cert). */
  detectionError: string | null;
  sslStatus: string | null;
}

export async function createWebsite(
  input: CreateWebsiteInput,
): Promise<CreatedWebsite> {
  await ensureDevSession();
  const dto = await apiPost<CreateWebsiteDto>("/websites", input);
  return {
    workspace: websiteToWorkspace(dto),
    detectedStackLabel: stackLabelOf(dto.detection.stack),
    candidates: dto.detection.candidates,
    detectionError: dto.detection.error,
    sslStatus: dto.ssl.status,
  };
}

export async function setWebsiteStack(
  websiteId: string,
  stackLabel: string,
): Promise<void> {
  await apiPatch(`/websites/${websiteId}/stack`, { stack_label: stackLabel });
}

export async function redetectStack(
  websiteId: string,
  allowInsecure = false,
): Promise<RedetectDto> {
  return apiPost<RedetectDto>(`/websites/${websiteId}/redetect`, {
    allow_insecure: allowInsecure,
  });
}

export async function fetchStackHint(websiteId: string): Promise<StackHintDto> {
  return apiGet<StackHintDto>(`/websites/${websiteId}/stack-hint`);
}

export async function checkSsl(websiteId: string): Promise<SslDto> {
  return apiGet<SslDto>(`/websites/${websiteId}/ssl`);
}

export async function archiveWebsite(
  websiteId: string,
  purge = false,
): Promise<void> {
  await apiDelete(`/websites/${websiteId}${purge ? "?purge=true" : ""}`);
}
