import { SERVER_BACKEND_ORIGIN } from "./api/client";

export type HealthResponse = { status: string };

/**
 * Appelee cote serveur (page /health) : a besoin d'une URL absolue.
 * `/health` est hors prefixe `/api/v1` (route racine dans app/main.py).
 */
export async function getBackendHealth(): Promise<HealthResponse> {
  const res = await fetch(`${SERVER_BACKEND_ORIGIN}/health`, { cache: "no-store" });
  if (!res.ok) {
    throw new Error(`Backend health check failed: ${res.status}`);
  }
  return res.json() as Promise<HealthResponse>;
}
