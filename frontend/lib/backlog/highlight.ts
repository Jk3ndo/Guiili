import { createHighlighter, type Highlighter } from "shiki";

import { getBacklog } from "@/lib/mock/backlog";
import { MOCK_WORKSPACES } from "@/lib/mock/workspaces";

/**
 * Fix snippets are static, so we tokenise every one on the server and hand
 * the client plain token data — no highlighter in the browser bundle.
 */

export interface FixToken {
  content: string;
  color?: string;
  /** shiki FontStyle bitfield: 1 italic, 2 bold, 4 underline. */
  fontStyle?: number;
}

export type HighlightedFixes = Record<string, FixToken[][]>;

let highlighterPromise: Promise<Highlighter> | null = null;

function getHighlighter(): Promise<Highlighter> {
  if (!highlighterPromise) {
    highlighterPromise = createHighlighter({
      themes: ["vitesse-dark"],
      langs: ["ts", "tsx", "js", "php", "json", "css"],
    });
  }
  return highlighterPromise;
}

export async function getHighlightedFixes(): Promise<HighlightedFixes> {
  const highlighter = await getHighlighter();
  const out: HighlightedFixes = {};

  for (const workspace of MOCK_WORKSPACES) {
    for (const item of getBacklog(workspace)) {
      if (!item.fix.code || !item.fix.lang || out[item.id]) continue;
      const { tokens } = highlighter.codeToTokens(item.fix.code, {
        lang: item.fix.lang,
        theme: "vitesse-dark",
      });
      out[item.id] = tokens.map((line) =>
        line.map((token) => ({
          content: token.content,
          color: token.color,
          fontStyle: token.fontStyle,
        })),
      );
    }
  }

  return out;
}
