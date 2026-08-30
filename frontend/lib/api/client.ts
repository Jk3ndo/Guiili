/**
 * Client HTTP minimal vers le backend FastAPI. `credentials: "include"` pour
 * transporter le cookie de session ; toute erreur (réseau, CORS, 4xx/5xx) est
 * remontée en `ApiError` pour que l'appelant bascule sur le fallback mocké.
 */

const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8020/api/v1";

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function request(path: string, init?: RequestInit): Promise<Response> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, {
      ...init,
      credentials: "include",
      headers: {
        Accept: "application/json",
        ...(init?.body ? { "Content-Type": "application/json" } : {}),
        ...init?.headers,
      },
    });
  } catch {
    throw new ApiError(0, "backend injoignable");
  }
  if (!response.ok) {
    throw new ApiError(response.status, `${response.status} ${response.statusText}`);
  }
  return response;
}

export async function apiGet<T>(path: string): Promise<T> {
  return (await request(path)).json() as Promise<T>;
}

export async function apiPost<T>(path: string, body?: unknown): Promise<T> {
  const init: RequestInit = { method: "POST" };
  if (body !== undefined) init.body = JSON.stringify(body);
  return (await request(path, init)).json() as Promise<T>;
}

export async function apiPatch<T>(path: string, body: unknown): Promise<T> {
  return (
    await request(path, { method: "PATCH", body: JSON.stringify(body) })
  ).json() as Promise<T>;
}

export interface DownloadedFile {
  blob: Blob;
  filename: string;
}

export async function apiDownload(path: string): Promise<DownloadedFile> {
  const response = await request(path);
  const disposition = response.headers.get("Content-Disposition") ?? "";
  const match = /filename="([^"]+)"/.exec(disposition);
  return { blob: await response.blob(), filename: match?.[1] ?? "download.json" };
}

/** Déclenche un téléchargement navigateur pour un Blob déjà en mémoire. */
export function saveBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.append(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}
