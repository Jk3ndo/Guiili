import type { FixToken } from "@/lib/backlog/highlight";

import { CopyButton } from "./copy-button";

function tokenStyle(token: FixToken): React.CSSProperties {
  const style: React.CSSProperties = { color: token.color };
  if (token.fontStyle && token.fontStyle & 1) style.fontStyle = "italic";
  if (token.fontStyle && token.fontStyle & 2) style.fontWeight = 600;
  if (token.fontStyle && token.fontStyle & 4)
    style.textDecoration = "underline";
  return style;
}

export function CodePanel({
  code,
  tokens,
  filename,
}: {
  code: string;
  /** shiki tokens when the snippet was highlighted server-side. */
  tokens?: FixToken[][];
  filename: string;
}) {
  return (
    <div className="overflow-hidden rounded-xl border border-white/[0.08] bg-[#0c1119]">
      <div className="flex items-center justify-between gap-3 border-b border-white/[0.06] bg-white/[0.02] px-3.5 py-2">
        <span className="truncate font-mono text-2xs text-ink-faint">
          {filename}
        </span>
        <CopyButton text={code} label="Copier le code" />
      </div>
      <pre className="max-h-[420px] overflow-auto px-3.5 py-3 font-mono text-xs leading-relaxed text-ink-muted">
        <code>
          {tokens
            ? tokens.map((line, i) => (
                <span key={i} className="block min-h-[1.6em]">
                  {line.map((token, j) => (
                    <span key={j} style={tokenStyle(token)}>
                      {token.content}
                    </span>
                  ))}
                </span>
              ))
            : code}
        </code>
      </pre>
    </div>
  );
}
