import { apiGet, ApiError } from "./client";
import type { DevWorkspaceDto } from "./dto";

/**
 * Résout un domaine de workspace mocké vers l'UUID de site du backend, via
 * l'amorçage dev `/dev/workspaces` (crée l'utilisateur + les 4 sites seedés et
 * pose le cookie de session au premier appel). Le résultat est mis en cache ;
 * un échec réseau vide le cache pour autoriser une nouvelle tentative.
 */

let cache: Promise<Map<string, DevWorkspaceDto>> | null = null;

function loadWorkspaces(): Promise<Map<string, DevWorkspaceDto>> {
  if (!cache) {
    cache = apiGet<DevWorkspaceDto[]>("/dev/workspaces")
      .then((list) => new Map(list.map((entry) => [entry.domain, entry])))
      .catch((error: unknown) => {
        cache = null;
        throw error;
      });
  }
  return cache;
}

export async function resolveWebsiteId(domain: string): Promise<string> {
  const workspaces = await loadWorkspaces();
  const entry = workspaces.get(domain);
  if (!entry) {
    throw new ApiError(404, `site « ${domain} » inconnu du backend`);
  }
  return entry.id;
}
