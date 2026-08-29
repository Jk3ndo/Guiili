"use client";

import { Check, Copy } from "lucide-react";
import { useCallback, useRef, useState } from "react";

import type { FixToken } from "@/lib/backlog/highlight";
import { copyText } from "@/lib/clipboard";
import type { IssueFix } from "@/lib/mock/backlog";
import { cn } from "@/lib/utils";

function tokenStyle(token: FixToken): React.CSSProperties {
  const style: React.CSSProperties = { color: token.color };
  if (token.fontStyle && token.fontStyle & 1) style.fontStyle = "italic";
  if (token.fontStyle && token.fontStyle & 2) style.fontWeight = 600;
  if (token.fontStyle && token.fontStyle & 4)
    style.textDecoration = "underline";
  return style;
}

export function FixBlock({
  fix,
  tokens,
}: {
  fix: IssueFix;
  tokens?: FixToken[][];
}) {
  const [copied, setCopied] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const codeTokens = fix.code ? tokens : undefined;

  const copy = useCallback(async () => {
    const text =
      fix.code ??
      (fix.steps ?? []).map((step, i) => `${i + 1}. ${step}`).join("\n");
    const ok = await copyText(text);
    if (!ok) return;
    setCopied(true);
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => setCopied(false), 2000);
  }, [fix]);

  return (
    <div className="mt-3 space-y-3 border-t border-white/[0.06] pt-3">
      <p className="max-w-2xl text-xs leading-relaxed text-ink-muted">
        {fix.summary}
      </p>

      {codeTokens ? (
        <div className="overflow-hidden rounded-xl border border-white/[0.08] bg-[#0c1119]">
          <div className="flex items-center justify-between border-b border-white/[0.06] bg-white/[0.02] px-4 py-2">
            <span className="font-mono text-2xs text-ink-faint">
              correctif.{fix.lang}
            </span>
          </div>
          <pre className="max-h-[380px] overflow-auto px-4 py-3.5 font-mono text-xs leading-relaxed text-ink-muted">
            <code>
              {codeTokens.map((line, i) => (
                <span key={i} className="block min-h-[1.6em]">
                  {line.map((token, j) => (
                    <span key={j} style={tokenStyle(token)}>
                      {token.content}
                    </span>
                  ))}
                </span>
              ))}
            </code>
          </pre>
        </div>
      ) : (
        <ol className="space-y-2.5 rounded-xl border border-white/[0.08] bg-surface/40 p-4">
          {fix.steps?.map((step, i) => (
            <li
              key={step}
              className="flex gap-3 text-xs leading-relaxed text-ink-muted"
            >
              <span className="mt-px flex size-4 shrink-0 items-center justify-center rounded-full border border-white/[0.12] font-mono text-2xs text-ink-faint tabular-nums">
                {i + 1}
              </span>
              <span>{step}</span>
            </li>
          ))}
        </ol>
      )}

      <button
        type="button"
        onClick={copy}
        className={cn(
          "inline-flex h-8 items-center gap-1.5 rounded-lg border px-2.5 text-2xs font-medium shadow-sm transition-colors",
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
        {copied ? "Copié" : "Copier le correctif"}
      </button>
    </div>
  );
}
