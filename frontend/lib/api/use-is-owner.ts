"use client";

import { useEffect, useState } from "react";

import { apiGet } from "./client";

interface WorkspaceMineDto {
  id: string;
  name: string;
  role: string;
}

/** Vrai si l'utilisateur courant est propriétaire du workspace donné. */
export function useIsOwner(realWorkspaceId: string | undefined): boolean {
  const [isOwner, setIsOwner] = useState(false);

  useEffect(() => {
    let cancelled = false;
    void apiGet<WorkspaceMineDto[]>("/workspaces/mine")
      .then((mine) => {
        if (cancelled) return;
        setIsOwner(mine.some((w) => w.id === realWorkspaceId && w.role === "owner"));
      })
      .catch(() => {
        if (!cancelled) setIsOwner(false);
      });
    return () => {
      cancelled = true;
    };
  }, [realWorkspaceId]);

  return isOwner;
}
