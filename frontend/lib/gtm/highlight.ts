import { createHighlighter, type Highlighter } from "shiki";

import {
  SNIPPETS,
  snippetKey,
  type HighlightedSnippets,
} from "@/lib/mock/gtm-export";

/**
 * Snippets are static, so we tokenise them once on the server and hand the
 * client plain token data (no markup, no highlighter in the browser bundle).
 */

let highlighterPromise: Promise<Highlighter> | null = null;

function getHighlighter(): Promise<Highlighter> {
  if (!highlighterPromise) {
    highlighterPromise = createHighlighter({
      themes: ["vitesse-dark"],
      langs: ["ts", "tsx", "js", "php"],
    });
  }
  return highlighterPromise;
}

export async function getHighlightedSnippets(): Promise<HighlightedSnippets> {
  const highlighter = await getHighlighter();
  const out: HighlightedSnippets = {};

  for (const snippet of SNIPPETS) {
    const { tokens } = highlighter.codeToTokens(snippet.code, {
      lang: snippet.lang,
      theme: "vitesse-dark",
    });

    out[snippetKey(snippet.stack, snippet.event)] = tokens.map((line) =>
      line.map((token) => ({
        content: token.content,
        color: token.color,
        fontStyle: token.fontStyle,
      })),
    );
  }

  return out;
}
