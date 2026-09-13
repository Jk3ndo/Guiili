"use client";

import { useEffect, useState } from "react";

import { apiGet, ApiError } from "@/lib/api/client";

interface StartResponse {
  authorization_url: string;
}

/**
 * `/auth/google/start` renvoie un JSON `{ authorization_url }` plutôt qu'une redirection HTTP
 * directe : un `<a href>` classique vers l'endpoint API n'obtiendrait donc que du JSON brut
 * dans l'onglet. Cette page intermédiaire fait le `fetch` puis effectue la redirection plein
 * navigateur elle-même via `window.location.href` (indispensable : le flow OAuth Google exige
 * une navigation réelle, qu'un simple `fetch` ne peut pas suivre en cross-origin).
 */
export default function GoogleLoginRedirectPage() {
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    apiGet<StartResponse>("/auth/google/start")
      .then(({ authorization_url }) => {
        if (!cancelled) window.location.href = authorization_url;
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setError(err instanceof ApiError ? err.message : "Connexion Google impossible");
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div className="flex min-h-screen items-center justify-center bg-canvas px-4 text-center">
      <div className="space-y-2">
        <p className="text-sm text-ink-muted">
          {error ?? "Redirection vers Google…"}
        </p>
        {error && (
          <a href="/login" className="block text-xs text-ink-muted underline hover:text-ink">
            Retour à la connexion
          </a>
        )}
      </div>
    </div>
  );
}
