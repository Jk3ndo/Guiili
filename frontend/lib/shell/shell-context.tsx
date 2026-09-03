"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";

import { listWebsites } from "@/lib/api/websites";
import { MOCK_WORKSPACES } from "@/lib/mock/workspaces";
import type { Workspace } from "@/lib/mock/types";

export const WORKSPACE_COOKIE = "cc_workspace";
const COOKIE_MAX_AGE = 60 * 60 * 24 * 365;

interface ShellContextValue {
  workspace: Workspace;
  /** Demo sites + real sites added by the user. */
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
  const [realWorkspaces, setRealWorkspaces] = useState<Workspace[]>([]);
  const [commandOpen, setCommandOpen] = useState(false);

  // Charge les sites réels de l'utilisateur (ceux ajoutés via "+ Ajouter un
  // domaine"). Échec silencieux : la démo reste utilisable hors-ligne.
  useEffect(() => {
    let active = true;
    void listWebsites()
      .then((sites) => {
        if (active) setRealWorkspaces(sites);
      })
      .catch(() => undefined);
    return () => {
      active = false;
    };
  }, []);

  const workspaces = useMemo<Workspace[]>(() => {
    // Le backend renvoie AUSSI les 4 sites de démo (créés pour l'utilisateur dev
    // par `/dev/workspaces`). On garde l'entrée mock (id/nom stables pour le
    // cookie) en l'enrichissant du `websiteId` réel ; les vrais nouveaux sites
    // sont ajoutés à la suite.
    const realByDomain = new Map(realWorkspaces.map((ws) => [ws.domain, ws]));
    const merged = MOCK_WORKSPACES.map((mock) => {
      const real = realByDomain.get(mock.domain);
      return real
        ? {
            ...mock,
            websiteId: real.websiteId,
            stack: real.stack,
            stackLabel: real.stackLabel,
            sslStatus: real.sslStatus,
            sslExpiresAt: real.sslExpiresAt,
          }
        : mock;
    });
    const mockDomains = new Set(MOCK_WORKSPACES.map((mock) => mock.domain));
    const extras = realWorkspaces.filter((ws) => !mockDomains.has(ws.domain));
    return [...merged, ...extras];
  }, [realWorkspaces]);

  // Cookie-backed (not localStorage) so the server layout reads the same value
  // on the next request — no post-mount effect, no flash.
  const setActiveWorkspace = useCallback((id: string) => {
    setWorkspaceId(id);
    document.cookie = `${WORKSPACE_COOKIE}=${id}; path=/; max-age=${COOKIE_MAX_AGE}; samesite=lax`;
  }, []);

  const addWorkspace = useCallback(
    (workspace: Workspace) => {
      setRealWorkspaces((current) => [
        ...current.filter((ws) => ws.id !== workspace.id),
        workspace,
      ]);
      setActiveWorkspace(workspace.id);
    },
    [setActiveWorkspace],
  );

  const updateWorkspace = useCallback(
    (id: string, patch: Partial<Workspace>) => {
      setRealWorkspaces((current) =>
        current.map((ws) => (ws.id === id ? { ...ws, ...patch } : ws)),
      );
    },
    [],
  );

  const removeWorkspace = useCallback((id: string) => {
    setRealWorkspaces((current) => current.filter((ws) => ws.id !== id));
    setWorkspaceId((activeId) =>
      activeId === id ? MOCK_WORKSPACES[0].id : activeId,
    );
  }, []);

  const value = useMemo<ShellContextValue>(
    () => ({
      workspace:
        workspaces.find((ws) => ws.id === workspaceId) ?? workspaces[0],
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

  return <ShellContext value={value}>{children}</ShellContext>;
}

export function useShell(): ShellContextValue {
  const ctx = useContext(ShellContext);
  if (!ctx) throw new Error("useShell must be used within <ShellProvider>");
  return ctx;
}
