import { apiGet, ApiError } from "./client";
import type { DevWorkspaceDto } from "./dto";

/**
 * Résout un domaine de site vers l'UUID backend.
 *
 * - Sites ajoutés par l'utilisateur (`POST /websites`) : enregistrés dans un
 *   registre en mémoire par le shell → résolution directe.
 * - Sites de démo : via l'amorçage dev `/dev/workspaces` (crée l'utilisateur +
 *   les 4 sites seedés et pose le cookie de session au premier appel).
 */

let cache: Promise<Map<string, DevWorkspaceDto>> | null = null;

/** domaine -> UUID backend, pour les sites réels ajoutés à chaud. */
const realRegistry = new Map<string, string>();

export function registerWebsite(domain: string, id: string): void {
  realRegistry.set(domain, id);
}

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

/**
 * Garantit qu'une session existe (l'amorçage dev pose le cookie). À appeler
 * avant tout appel authentifié quand aucun site de démo n'a encore été touché.
 */
export async function ensureDevSession(): Promise<void> {
  await loadWorkspaces().catch(() => undefined);
}

export async function resolveWebsiteId(domain: string): Promise<string> {
  const real = realRegistry.get(domain);
  if (real) return real;

  const workspaces = await loadWorkspaces();
  const entry = workspaces.get(domain);
  if (!entry) {
    throw new ApiError(404, `site « ${domain} » inconnu du backend`);
  }
  return entry.id;
}
