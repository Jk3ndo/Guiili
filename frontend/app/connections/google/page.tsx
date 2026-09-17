"use client";

import { Suspense, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";

import { apiGet, ApiError } from "@/lib/api/client";

interface StartResponse {
  authorization_url: string;
}

function ConnectGoogleRedirect() {
  const searchParams = useSearchParams();
  const workspaceId = searchParams.get("workspace_id");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!workspaceId) {
      return;
    }
    let cancelled = false;
    apiGet<StartResponse>(`/connections/google/start?workspace_id=${workspaceId}`)
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
  }, [workspaceId]);

  const message = !workspaceId ? "workspace manquant" : error ?? "Redirection vers Google…";

  return (
    <div className="flex min-h-screen items-center justify-center bg-canvas px-4 text-center">
      <div className="space-y-2">
        <p className="text-sm text-ink-muted">{message}</p>
        {(!workspaceId || error) && (
          <a href="/connections" className="block text-xs text-ink-muted underline hover:text-ink">
            Retour aux connexions
          </a>
        )}
      </div>
    </div>
  );
}

export default function ConnectGoogleRedirectPage() {
  return (
    <Suspense fallback={null}>
      <ConnectGoogleRedirect />
    </Suspense>
  );
}
