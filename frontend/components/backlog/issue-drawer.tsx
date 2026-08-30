"use client";

import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import type { FixToken } from "@/lib/backlog/highlight";
import { relativeDays } from "@/lib/format";
import {
  CATEGORY_LABEL,
  SEVERITY_LABEL,
  STATUS_LABEL,
  type IssueItem,
  type IssueSeverity,
} from "@/lib/mock/backlog";
import { cn } from "@/lib/utils";

import { CodePanel } from "./code-panel";
import { CopyButton } from "./copy-button";

const SEVERITY_DOT: Record<IssueSeverity, string> = {
  critical: "bg-danger",
  warning: "bg-warn",
  info: "bg-ink-faint",
};

function Field({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div className="space-y-1.5">
      <p className="text-2xs font-medium text-ink-faint">{label}</p>
      {children}
    </div>
  );
}

export function IssueDrawer({
  item,
  tokens,
  onOpenChange,
}: {
  item: IssueItem | null;
  tokens?: FixToken[][];
  onOpenChange: (open: boolean) => void;
}) {
  return (
    <Sheet open={item !== null} onOpenChange={onOpenChange}>
      <SheetContent
        side="right"
        className="w-full gap-0 border-l-white/[0.1] bg-surface p-0 sm:max-w-xl"
      >
        {item && (
          <>
            <SheetHeader className="gap-2.5 border-b border-white/[0.06] p-5 pr-12">
              <div className="flex flex-wrap items-center gap-2 text-2xs">
                <span className="flex items-center gap-1.5 font-medium text-ink-muted">
                  <span
                    className={cn(
                      "size-1.5 rounded-full",
                      SEVERITY_DOT[item.severity],
                    )}
                  />
                  {SEVERITY_LABEL[item.severity]}
                </span>
                <span className="text-ink-faint">·</span>
                <span className="inline-flex h-[18px] items-center rounded border border-hairline bg-white/[0.03] px-1.5 font-mono text-ink-muted">
                  {CATEGORY_LABEL[item.category]}
                </span>
                <span className="text-ink-faint">·</span>
                <span className="text-ink-faint">
                  {STATUS_LABEL[item.status]}
                </span>
                <span className="text-ink-faint">·</span>
                <span className="text-ink-faint">
                  détecté {relativeDays(item.detectedDaysAgo)}
                </span>
              </div>
              <SheetTitle className="text-sm leading-snug font-semibold text-ink">
                {item.title}
              </SheetTitle>
              <SheetDescription className="text-xs leading-relaxed text-ink-muted">
                {item.context}
              </SheetDescription>
            </SheetHeader>

            <div className="flex-1 space-y-5 overflow-y-auto p-5">
              <Field label="Impact">
                <p className="text-xs leading-relaxed text-ink">{item.impact}</p>
              </Field>

              <Field label="Recommandation">
                <p className="text-xs leading-relaxed text-ink-muted">
                  {item.fix.summary}
                </p>
              </Field>

              {item.fix.file && (
                <Field label="Fichier cible">
                  <span className="inline-block rounded-md border border-white/[0.08] bg-white/[0.03] px-2 py-1 font-mono text-2xs text-ink-muted">
                    {item.fix.file}
                  </span>
                </Field>
              )}

              {item.fix.code ? (
                <Field label="Correctif">
                  <CodePanel
                    code={item.fix.code}
                    tokens={tokens}
                    filename={item.fix.file ?? `correctif.${item.fix.lang ?? "txt"}`}
                  />
                </Field>
              ) : item.fix.steps ? (
                <Field label="Marche à suivre">
                  <ol className="space-y-2.5 rounded-xl border border-white/[0.08] bg-surface/40 p-4">
                    {item.fix.steps.map((step, i) => (
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
                  <div className="mt-3">
                    <CopyButton
                      text={item.fix.steps
                        .map((step, i) => `${i + 1}. ${step}`)
                        .join("\n")}
                      label="Copier le correctif"
                    />
                  </div>
                </Field>
              ) : null}
            </div>
          </>
        )}
      </SheetContent>
    </Sheet>
  );
}
