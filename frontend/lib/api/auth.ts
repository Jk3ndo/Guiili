import { API_BASE, apiGet, apiPost, apiPostNoContent, ApiError } from "./client";

export interface MeDto {
  id: string;
  email: string;
  display_name: string | null;
}

export async function login(email: string, password: string): Promise<void> {
  await apiPost("/auth/login", { email, password });
}

export async function register(
  email: string,
  password: string,
  displayName: string,
): Promise<void> {
  await apiPost("/auth/register", {
    email,
    password,
    display_name: displayName || null,
  });
}

export async function logout(): Promise<void> {
  await apiPostNoContent("/auth/logout");
}

/** Client Component / Client-side : s'appuie sur le cookie de session transmis par le navigateur. */
export async function fetchMe(): Promise<MeDto | null> {
  try {
    return await apiGet<MeDto>("/auth/me");
  } catch (error) {
    if (error instanceof ApiError && error.status === 401) return null;
    throw error;
  }
}

/**
 * Variante Server Component : `apiGet` s'appuie sur `fetch(..., { credentials: "include" })`,
 * qui ne s'applique qu'aux requêtes émises par le navigateur — un `fetch` déclenché côté
 * serveur (dans un layout/page async) ne transmet pas automatiquement le cookie de la
 * requête entrante. Il faut donc lire le cookie de session via `cookies()` (next/headers)
 * dans l'appelant et le transmettre ici explicitement en en-tête `Cookie`.
 */
export async function fetchMeServer(cookieHeader: string): Promise<MeDto | null> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE}/auth/me`, {
      headers: { Accept: "application/json", Cookie: cookieHeader },
      cache: "no-store",
    });
  } catch {
    throw new ApiError(0, "backend injoignable");
  }
  if (response.status === 401) return null;
  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`;
    try {
      const payload = (await response.clone().json()) as { detail?: unknown };
      if (typeof payload.detail === "string" && payload.detail) detail = payload.detail;
    } catch {
      // corps non-JSON : on garde le statut brut
    }
    throw new ApiError(response.status, detail);
  }
  return (await response.json()) as MeDto;
}
