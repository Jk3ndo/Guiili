/**
 * Shapes the shell renders today from local fixtures. When the API lands,
 * only `lib/mock/*` gets swapped — components import from here, not from fetch.
 */

export type StackId = "nextjs" | "wordpress" | "angular" | "vue" | "other";

export type TokenStatus = "connected" | "needs_reauth";

export interface Workspace {
  id: string;
  /** Display name for the tracked site. */
  name: string;
  /** Bare domain, e.g. "boutique-verte.fr". */
  domain: string;
  /** Detected front-end stack — drives the sidebar badge. */
  stack: StackId;
  /** Health of the Google connection(s) backing this site. */
  tokenStatus: TokenStatus;
}
