import type { Workspace } from "./types";

/**
 * Stand-in for `GET /api/workspaces/:id/connections`. Deterministic per
 * workspace and consistent with the ids used elsewhere in the mock (GTM
 * containers, GA4 properties, GSC domains). Read-only scopes only.
 */

export type GoogleScope = "analytics.readonly" | "webmasters.readonly";

export type IdentityStatus = "active" | "needs_reauth";

export interface GoogleIdentity {
  id: string;
  email: string;
  /** Human note on the account's role — agency vs. client, etc. */
  role: string;
  scopes: GoogleScope[];
  status: IdentityStatus;
  /** Shown under the status pill. For needs_reauth, why it broke. */
  statusNote: string;
  lastSyncHoursAgo: number;
}

export type ResourceType = "ga4" | "gtm" | "gsc";

export interface ResourceOption {
  /** Canonical id: "properties/447213908", "GTM-PK2X9QM", "sc-domain:x". */
  id: string;
  /** Friendly name shown above the id. */
  label: string;
  /** Google account that exposes this resource. */
  identityEmail: string;
}

export interface ResourceLink {
  type: ResourceType;
  /** Currently assigned option id, or null when nothing is linked. */
  linkedId: string | null;
  /** Everything discovered for this type across the connected identities. */
  options: ResourceOption[];
}

export interface ConnectionsData {
  identities: GoogleIdentity[];
  resources: ResourceLink[];
}

export const RESOURCE_META: Record<
  ResourceType,
  { name: string; noun: string }
> = {
  ga4: { name: "Google Analytics 4", noun: "Propriété liée" },
  gtm: { name: "Google Tag Manager", noun: "Conteneur lié" },
  gsc: { name: "Google Search Console", noun: "Domaine vérifié" },
};

export function linkedOption(link: ResourceLink): ResourceOption | null {
  return link.options.find((option) => option.id === link.linkedId) ?? null;
}

const AGENCY = "dev.agence@gmail.com";

const FIXTURES: Record<string, ConnectionsData> = {
  ws_boutique_verte: {
    identities: [
      {
        id: "id_dev_agence",
        email: AGENCY,
        role: "Agence — accès délégué",
        scopes: ["analytics.readonly", "webmasters.readonly"],
        status: "active",
        statusNote: "Jeton valide · rotation dans 5 jours",
        lastSyncHoursAgo: 3,
      },
      {
        id: "id_client_perso",
        email: "client.perso@gmail.com",
        role: "Compte du client",
        scopes: ["analytics.readonly"],
        status: "active",
        statusNote: "Jeton valide · rotation dans 21 jours",
        lastSyncHoursAgo: 12,
      },
    ],
    resources: [
      {
        type: "ga4",
        linkedId: "properties/447213908",
        options: [
          {
            id: "properties/447213908",
            label: "Boutique Prod",
            identityEmail: "client.perso@gmail.com",
          },
          {
            id: "properties/501882145",
            label: "Boutique Staging",
            identityEmail: "client.perso@gmail.com",
          },
          {
            id: "properties/338100771",
            label: "Blog éditorial",
            identityEmail: AGENCY,
          },
        ],
      },
      {
        type: "gtm",
        linkedId: "GTM-PK2X9QM",
        options: [
          {
            id: "GTM-PK2X9QM",
            label: "Web Container",
            identityEmail: AGENCY,
          },
          {
            id: "GTM-9KX2P0M",
            label: "Serveur (sGTM)",
            identityEmail: AGENCY,
          },
        ],
      },
      {
        type: "gsc",
        linkedId: "sc-domain:boutique-verte.fr",
        options: [
          {
            id: "sc-domain:boutique-verte.fr",
            label: "Propriété de domaine",
            identityEmail: AGENCY,
          },
          {
            id: "https://boutique-verte.fr/",
            label: "Préfixe d'URL",
            identityEmail: AGENCY,
          },
        ],
      },
    ],
  },

  ws_atelier_nord: {
    identities: [
      {
        id: "id_dev_agence",
        email: AGENCY,
        role: "Agence — accès délégué",
        scopes: ["analytics.readonly", "webmasters.readonly"],
        status: "needs_reauth",
        statusNote: "Jeton Search Console expiré il y a 6 jours (rotation 7 j)",
        lastSyncHoursAgo: 148,
      },
      {
        id: "id_atelier_nord",
        email: "atelier.nord@gmail.com",
        role: "Compte du client",
        scopes: ["analytics.readonly"],
        status: "active",
        statusNote: "Jeton valide · rotation dans 12 jours",
        lastSyncHoursAgo: 40,
      },
    ],
    resources: [
      {
        type: "ga4",
        linkedId: "properties/512006644",
        options: [
          {
            id: "properties/512006644",
            label: "Atelier Nord",
            identityEmail: "atelier.nord@gmail.com",
          },
          {
            id: "properties/512006701",
            label: "Atelier Nord — App mobile",
            identityEmail: "atelier.nord@gmail.com",
          },
        ],
      },
      {
        type: "gtm",
        linkedId: "GTM-T7R4WZ2",
        options: [
          {
            id: "GTM-T7R4WZ2",
            label: "Web Container",
            identityEmail: AGENCY,
          },
        ],
      },
      {
        type: "gsc",
        linkedId: "sc-domain:atelier-nord.com",
        options: [
          {
            id: "sc-domain:atelier-nord.com",
            label: "Propriété de domaine",
            identityEmail: AGENCY,
          },
          {
            id: "https://www.atelier-nord.com/",
            label: "Préfixe d'URL",
            identityEmail: AGENCY,
          },
        ],
      },
    ],
  },

  ws_studio_lumen: {
    identities: [
      {
        id: "id_studio_lumen",
        email: "studio.lumen@gmail.com",
        role: "Compte du client",
        scopes: ["analytics.readonly", "webmasters.readonly"],
        status: "active",
        statusNote: "Jeton valide · rotation dans 9 jours",
        lastSyncHoursAgo: 9,
      },
      {
        id: "id_dev_agence",
        email: AGENCY,
        role: "Agence — accès délégué",
        scopes: ["analytics.readonly", "webmasters.readonly"],
        status: "active",
        statusNote: "Jeton valide · rotation dans 18 jours",
        lastSyncHoursAgo: 5,
      },
    ],
    resources: [
      {
        type: "ga4",
        linkedId: "properties/399820015",
        options: [
          {
            id: "properties/399820015",
            label: "Studio Lumen",
            identityEmail: "studio.lumen@gmail.com",
          },
          {
            id: "properties/399820088",
            label: "Studio Lumen — Docs",
            identityEmail: AGENCY,
          },
        ],
      },
      {
        type: "gtm",
        linkedId: "GTM-9LMN3KD",
        options: [
          {
            id: "GTM-9LMN3KD",
            label: "Web Container",
            identityEmail: AGENCY,
          },
        ],
      },
      {
        type: "gsc",
        linkedId: "sc-domain:studiolumen.io",
        options: [
          {
            id: "sc-domain:studiolumen.io",
            label: "Propriété de domaine",
            identityEmail: "studio.lumen@gmail.com",
          },
          {
            id: "https://studiolumen.io/",
            label: "Préfixe d'URL",
            identityEmail: "studio.lumen@gmail.com",
          },
        ],
      },
    ],
  },

  ws_cap_horizon: {
    identities: [
      {
        id: "id_cap_horizon",
        email: "cap.horizon@gmail.com",
        role: "Compte du client",
        scopes: ["analytics.readonly", "webmasters.readonly"],
        status: "active",
        statusNote: "Jeton valide · rotation dans 14 jours",
        lastSyncHoursAgo: 20,
      },
      {
        id: "id_dev_agence",
        email: AGENCY,
        role: "Agence — accès délégué",
        scopes: ["analytics.readonly"],
        status: "active",
        statusNote: "Jeton valide · rotation dans 7 jours",
        lastSyncHoursAgo: 6,
      },
    ],
    resources: [
      {
        type: "ga4",
        linkedId: "properties/462119003",
        options: [
          {
            id: "properties/462119003",
            label: "Cap Horizon",
            identityEmail: "cap.horizon@gmail.com",
          },
          {
            id: "properties/462119050",
            label: "Cap Horizon — Landing",
            identityEmail: AGENCY,
          },
        ],
      },
      {
        type: "gtm",
        linkedId: "GTM-CH5PQ8V",
        options: [
          {
            id: "GTM-CH5PQ8V",
            label: "Web Container",
            identityEmail: "cap.horizon@gmail.com",
          },
        ],
      },
      {
        type: "gsc",
        linkedId: "sc-domain:cap-horizon.co",
        options: [
          {
            id: "sc-domain:cap-horizon.co",
            label: "Propriété de domaine",
            identityEmail: "cap.horizon@gmail.com",
          },
          {
            id: "https://cap-horizon.co/",
            label: "Préfixe d'URL",
            identityEmail: "cap.horizon@gmail.com",
          },
        ],
      },
    ],
  },
};

export function getConnections(workspace: Workspace): ConnectionsData {
  return FIXTURES[workspace.id] ?? FIXTURES.ws_boutique_verte;
}
