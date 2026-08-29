import type { Workspace } from "./types";

/**
 * Stand-in for `GET /api/workspaces`. Deliberately mixed stacks and token
 * states so the sidebar switcher and health indicator show every variant.
 */
export const MOCK_WORKSPACES: Workspace[] = [
  {
    id: "ws_boutique_verte",
    name: "Boutique Verte",
    domain: "boutique-verte.fr",
    stack: "nextjs",
    tokenStatus: "connected",
  },
  {
    id: "ws_atelier_nord",
    name: "Atelier Nord",
    domain: "atelier-nord.com",
    stack: "wordpress",
    tokenStatus: "needs_reauth",
  },
  {
    id: "ws_studio_lumen",
    name: "Studio Lumen",
    domain: "studiolumen.io",
    stack: "vue",
    tokenStatus: "connected",
  },
  {
    id: "ws_cap_horizon",
    name: "Cap Horizon",
    domain: "cap-horizon.co",
    stack: "angular",
    tokenStatus: "connected",
  },
];

export const DEFAULT_WORKSPACE_ID = MOCK_WORKSPACES[0].id;

export function getWorkspace(id: string): Workspace {
  return MOCK_WORKSPACES.find((w) => w.id === id) ?? MOCK_WORKSPACES[0];
}
