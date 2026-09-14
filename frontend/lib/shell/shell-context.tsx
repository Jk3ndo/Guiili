"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";

import { EmptyWorkspaceState } from "@/components/shell/empty-workspace-state";
import { listWebsites } from "@/lib/api/websites";
import type { Workspace } from "@/lib/mock/types";

export const WORKSPACE_COOKIE = "cc_workspace";
const COOKIE_MAX_AGE = 60 * 60 * 24 * 365;

interface ShellContextValue {
  workspace: Workspace;
  /** Real sites belonging to the current user. */
  workspaces: Workspace[];
  setActiveWorkspace: (id: string) => void;
  /** Register a freshly created site and switch to it. */
  addWorkspace: (workspace: Workspace) => void;
  /** Patch a real site in place (stack confirmed, SSL re-checked…). */
  updateWorkspace: (id: string, patch: Partial<Workspace>) => void;
  /** Drop an archived site and fall back to the first workspace. */
  removeWorkspace: (id: string) => void;
  commandOpen: boolean;
  setCommandOpen: (open: boolean) => void;
}

const ShellContext = createContext<ShellContextValue | null>(null);

export function ShellProvider({
  initialWorkspaceId,
  children,
}: {
  initialWorkspaceId: string;
  children: React.ReactNode;
}) {
  const [workspaceId, setWorkspaceId] = useState(initialWorkspaceId);
  // `null` = pas encore chargé (premier rendu) ; `[]` = chargé, aucun site réel.
  const [realWorkspaces, setRealWorkspaces] = useState<Workspace[] | null>(null);
  const [commandOpen, setCommandOpen] = useState(false);

  // Charge les sites réels de l'utilisateur connecté (ceux ajoutés via
  // "+ Ajouter un domaine"). Ce sont les SEULS sites affichés — voir plus bas
  // pour le rendu pendant le chargement / si la liste est vide.
  useEffect(() => {
    let active = true;
    void listWebsites()
      .then((sites) => {
        if (active) setRealWorkspaces(sites);
      })
      .catch(() => {
        if (active) setRealWorkspaces([]);
      });
    return () => {
      active = false;
    };
  }, []);

  // `realWorkspaces ?? []` recreerait un nouveau tableau (donc une nouvelle
  // reference) a chaque rendu tant que `realWorkspaces` est null — useMemo
  // stabilise la reference pour le useMemo de `value` plus bas.
  const workspaces = useMemo(() => realWorkspaces ?? [], [realWorkspaces]);

  // Cookie-backed (not localStorage) so the server layout reads the same value
  // on the next request — no post-mount effect, no flash.
  const setActiveWorkspace = useCallback((id: string) => {
    setWorkspaceId(id);
    document.cookie = `${WORKSPACE_COOKIE}=${id}; path=/; max-age=${COOKIE_MAX_AGE}; samesite=lax`;
  }, []);

  const addWorkspace = useCallback(
    (workspace: Workspace) => {
      setRealWorkspaces((current) => [
        ...(current ?? []).filter((ws) => ws.id !== workspace.id),
        workspace,
      ]);
      setActiveWorkspace(workspace.id);
    },
    [setActiveWorkspace],
  );

  const updateWorkspace = useCallback(
    (id: string, patch: Partial<Workspace>) => {
      setRealWorkspaces((current) =>
        (current ?? []).map((ws) => (ws.id === id ? { ...ws, ...patch } : ws)),
      );
    },
    [],
  );

  const removeWorkspace = useCallback((id: string) => {
    setRealWorkspaces((current) => (current ?? []).filter((ws) => ws.id !== id));
    setWorkspaceId((activeId) => (activeId === id ? "" : activeId));
  }, []);

  const value = useMemo<ShellContextValue>(
    () => ({
      workspace:
        (workspaces.find((ws) => ws.id === workspaceId) ?? workspaces[0]) as Workspace,
      workspaces,
      setActiveWorkspace,
      addWorkspace,
      updateWorkspace,
      removeWorkspace,
      commandOpen,
      setCommandOpen,
    }),
    [
      workspaces,
      workspaceId,
      setActiveWorkspace,
      addWorkspace,
      updateWorkspace,
      removeWorkspace,
      commandOpen,
    ],
  );

  // Chargement en cours : rien de significatif à montrer encore (pas de
  // sidebar/chrome tant qu'on ne sait pas si l'utilisateur a des sites).
  if (realWorkspaces === null) {
    return <div className="min-h-screen bg-canvas" />;
  }

  // Aucun site réel : pas de shell (sidebar/topbar) tant qu'il n'y a rien à
  // piloter — un écran dédié invite à ajouter le premier site.
  if (workspaces.length === 0) {
    return (
      <ShellContext value={value}>
        <EmptyWorkspaceState />
      </ShellContext>
    );
  }

  return <ShellContext value={value}>{children}</ShellContext>;
}

export function useShell(): ShellContextValue {
  const ctx = useContext(ShellContext);
  if (!ctx) throw new Error("useShell must be used within <ShellProvider>");
  return ctx;
}
