"use client";

import { Check, Copy } from "lucide-react";
import { useCallback, useRef, useState } from "react";

import type { CodeToken } from "@/lib/mock/gtm-export";
import { cn } from "@/lib/utils";

interface CodeBlockProps {
  /** Raw source, copied verbatim to the clipboard. */
  code: string;
  /** Server-tokenised lines from shiki. Absent -> plain rendering (API source). */
  lines?: CodeToken[][];
  filename: string;
}

async function writeToClipboard(text: string): Promise<boolean> {
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text);
      return true;
    }
  } catch {
    // fall through to the legacy path
  }
  try {
    const area = document.createElement("textarea");
    area.value = text;
    area.setAttribute("readonly", "");
    area.style.position = "fixed";
    area.style.opacity = "0";
    document.body.append(area);
    area.select();
    const ok = document.execCommand("copy");
    area.remove();
    return ok;
  } catch {
    return false;
  }
}

function tokenStyle(token: CodeToken): React.CSSProperties {
  const style: React.CSSProperties = { color: token.color };
  if (token.fontStyle && token.fontStyle & 1) style.fontStyle = "italic";
  if (token.fontStyle && token.fontStyle & 2) style.fontWeight = 600;
  if (token.fontStyle && token.fontStyle & 4)
    style.textDecoration = "underline";
  return style;
}

export function CodeBlock({ code, lines, filename }: CodeBlockProps) {
  const [copied, setCopied] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const copy = useCallback(async () => {
    const ok = await writeToClipboard(code);
    if (!ok) return;
    setCopied(true);
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => setCopied(false), 2000);
  }, [code]);

  return (
    <div className="overflow-hidden rounded-xl border border-white/[0.08] bg-[#0c1119]">
      <div className="flex items-center justify-between gap-3 border-b border-white/[0.06] bg-white/[0.02] px-4 py-2">
        <span className="truncate font-mono text-2xs text-ink-faint">
          {filename}
        </span>
        <button
          type="button"
          onClick={copy}
          className={cn(
            "inline-flex shrink-0 items-center gap-1.5 rounded-md border px-2 py-1 text-2xs font-medium transition-colors",
            copied
              ? "border-transparent text-ok"
              : "border-white/[0.08] bg-white/[0.03] text-ink-muted hover:bg-white/[0.06] hover:text-ink",
          )}
        >
          {copied ? (
            <Check className="size-3.5" />
          ) : (
            <Copy className="size-3.5" />
          )}
          {copied ? "Copié" : "Copier le code"}
        </button>
      </div>
      <pre className="max-h-[440px] overflow-auto px-4 py-3.5 font-mono text-xs leading-relaxed text-ink-muted">
        <code>
          {lines
            ? lines.map((line, i) => (
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
