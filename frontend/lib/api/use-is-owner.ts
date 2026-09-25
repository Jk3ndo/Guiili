"use client";

import { useEffect, useState } from "react";

import { apiGet } from "./client";

interface WorkspaceMineDto {
  id: string;
  name: string;
  role: string;
}

/**
 * Vrai si l'utilisateur courant est propriétaire du workspace donné.
 * Fail-closed : faux tant que la réponse n'est pas arrivée pour CE workspace, et en cas
 * d'erreur ; le résultat mémorisé porte l'id du workspace pour qu'un « vrai » du
 * workspace précédent ne survive pas pendant le fetch suivant.
 */
export function useIsOwner(realWorkspaceId: string | undefined): boolean {
  const [result, setResult] = useState<{ id: string; owner: boolean } | null>(null);

  useEffect(() => {
    if (realWorkspaceId === undefined) return;
    let cancelled = false;
    void apiGet<WorkspaceMineDto[]>("/workspaces/mine")
      .then((mine) => {
        if (cancelled) return;
        setResult({
          id: realWorkspaceId,
          owner: mine.some((w) => w.id === realWorkspaceId && w.role === "owner"),
        });
      })
      .catch(() => {
        if (!cancelled) setResult({ id: realWorkspaceId, owner: false });
      });
    return () => {
      cancelled = true;
    };
  }, [realWorkspaceId]);

  return realWorkspaceId !== undefined && result?.id === realWorkspaceId && result.owner;
}
