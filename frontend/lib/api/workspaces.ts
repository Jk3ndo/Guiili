import { ApiError } from "./client";

/**
 * Résout un domaine de site vers l'UUID backend.
 *
 * Le registre est peuplé par `listWebsites()`/`createWebsite()` (voir
 * `websiteToWorkspace` dans `./websites.ts`), qui enregistrent chaque site
 * réel de l'utilisateur dès qu'il est chargé — le shell attend que cette
 * liste soit chargée avant de monter les vues qui en dépendent (voir
 * `ShellProvider`), donc le registre est déjà prêt au moment où une vue
 * appelle `resolveWebsiteId`.
 *
 * ⚠️ Avant l'authentification réelle, ce module passait par un amorçage dev
 * (`GET /dev/workspaces`) qui créait un utilisateur fixe et — plus grave —
 * reposait le cookie de session à chaque appel, écrasant silencieusement la
 * session de n'importe quel utilisateur réellement connecté. Retiré : plus
 * aucun appel ne doit re-authentifier l'utilisateur à son insu.
 */

const realRegistry = new Map<string, string>();

export function registerWebsite(domain: string, id: string): void {
  realRegistry.set(domain, id);
}

export async function resolveWebsiteId(domain: string): Promise<string> {
  const real = realRegistry.get(domain);
  if (!real) {
    throw new ApiError(404, `site « ${domain} » inconnu du backend`);
  }
  return real;
}
