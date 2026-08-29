"use client";

import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
} from "react";

import { getWorkspace } from "@/lib/mock/workspaces";
import type { Workspace } from "@/lib/mock/types";

export const WORKSPACE_COOKIE = "cc_workspace";
const COOKIE_MAX_AGE = 60 * 60 * 24 * 365;

interface ShellContextValue {
  workspace: Workspace;
  setActiveWorkspace: (id: string) => void;
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
  const [commandOpen, setCommandOpen] = useState(false);

  // Cookie-backed (not localStorage) so the server layout reads the same value
  // on the next request — no post-mount effect, no flash.
  const setActiveWorkspace = useCallback((id: string) => {
    setWorkspaceId(id);
    document.cookie = `${WORKSPACE_COOKIE}=${id}; path=/; max-age=${COOKIE_MAX_AGE}; samesite=lax`;
  }, []);

  const value = useMemo<ShellContextValue>(
    () => ({
      workspace: getWorkspace(workspaceId),
      setActiveWorkspace,
      commandOpen,
      setCommandOpen,
    }),
    [workspaceId, setActiveWorkspace, commandOpen],
  );

  return <ShellContext value={value}>{children}</ShellContext>;
}

export function useShell(): ShellContextValue {
  const ctx = useContext(ShellContext);
  if (!ctx) throw new Error("useShell must be used within <ShellProvider>");
  return ctx;
}
