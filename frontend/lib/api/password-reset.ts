import { apiPost } from "./client";

/**
 * `POST /auth/password-reset/request` renvoie toujours 200 `{"status":"ok"}`,
 * que l'email corresponde à un compte ou non (propriété de sécurité côté
 * backend : ne jamais révéler l'existence d'un compte). Le frontend ne doit
 * pas essayer de distinguer les deux cas.
 */
export async function requestPasswordReset(email: string): Promise<void> {
  await apiPost("/auth/password-reset/request", { email });
}

/**
 * `POST /auth/password-reset/confirm` renvoie 200 `{"status":"ok"}` si le
 * jeton est valide, ou lève une erreur 400 (`detail: "lien invalide ou
 * expire"`) si le jeton est invalide, déjà utilisé ou expiré — remontée en
 * `ApiError` par `apiPost`.
 */
export async function confirmPasswordReset(
  token: string,
  newPassword: string,
): Promise<void> {
  await apiPost("/auth/password-reset/confirm", {
    token,
    new_password: newPassword,
  });
}
