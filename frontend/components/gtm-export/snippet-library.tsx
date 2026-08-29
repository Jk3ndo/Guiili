"use client";

import { FolderTree } from "lucide-react";
import { Tabs as TabsPrimitive } from "radix-ui";
import { useState } from "react";

import {
  GTM_EVENTS,
  GTM_STACKS,
  gtmStackForWorkspace,
  snippetFor,
  snippetKey,
  type GtmEventId,
  type GtmStackId,
  type HighlightedSnippets,
} from "@/lib/mock/gtm-export";
import type { Workspace } from "@/lib/mock/types";
import { cn } from "@/lib/utils";

import { CodeBlock } from "./code-block";

export function SnippetLibrary({
  workspace,
  highlighted,
}: {
  workspace: Workspace;
  highlighted: HighlightedSnippets;
}) {
  const detected = gtmStackForWorkspace(workspace.stack);
  const [stack, setStack] = useState<GtmStackId>(detected);
  const [event, setEvent] = useState<GtmEventId>("purchase");

  const detectedLabel = GTM_STACKS.find((s) => s.id === detected)?.label;

  return (
    <section className="space-y-4">
      <div className="space-y-1">
        <h2 className="text-sm font-medium text-ink">
          Instrumentation du code client
        </h2>
        <p className="max-w-2xl text-xs leading-relaxed text-ink-muted">
          Snippets <span className="font-mono">dataLayer.push</span> prêts à
          coller, générés pour votre stack et l&apos;événement à suivre. Stack
          détectée&nbsp;: {detectedLabel}.
        </p>
      </div>

      <TabsPrimitive.Root
        value={stack}
        onValueChange={(value) => setStack(value as GtmStackId)}
      >
        <TabsPrimitive.List className="flex gap-1 border-b border-white/[0.08]">
          {GTM_STACKS.map((option) => (
            <TabsPrimitive.Trigger
              key={option.id}
              value={option.id}
              className={cn(
                "-mb-px border-b-2 border-transparent px-3 py-2 text-xs font-medium text-ink-muted transition-colors hover:text-ink",
                "data-[state=active]:border-b-zinc-200 data-[state=active]:text-ink",
              )}
            >
              {option.label}
            </TabsPrimitive.Trigger>
          ))}
        </TabsPrimitive.List>

        <div className="mt-4 flex flex-wrap gap-1.5">
          {GTM_EVENTS.map((option) => (
            <button
              key={option.id}
              type="button"
              onClick={() => setEvent(option.id)}
              className={cn(
                "rounded-lg border px-2.5 py-1 text-xs font-medium transition-colors",
                event === option.id
                  ? "border-white/[0.14] bg-white/[0.06] text-ink"
                  : "border-white/[0.08] bg-white/[0.02] text-ink-muted hover:text-ink",
              )}
            >
              {option.label}
            </button>
          ))}
        </div>

        {GTM_STACKS.map((option) => {
          const snippet = snippetFor(option.id, event);
          const lines = highlighted[snippetKey(option.id, event)] ?? [];
          return (
            <TabsPrimitive.Content
              key={option.id}
              value={option.id}
              className="mt-4 space-y-3 focus-visible:outline-none"
            >
              <CodeBlock
                code={snippet.code}
                lines={lines}
                filename={snippet.filename}
              />
              <div className="flex items-start gap-2.5 rounded-lg border border-white/[0.08] bg-white/[0.02] px-3.5 py-3">
                <FolderTree className="mt-0.5 size-4 shrink-0 text-ink-faint" />
                <div className="space-y-1">
                  <p className="text-xs text-ink-muted">
                    Emplacement recommandé&nbsp;·{" "}
                    <span className="font-mono text-ink">
                      {snippet.location}
                    </span>
                  </p>
                  <p className="text-xs leading-relaxed text-ink-muted">
                    {snippet.locationNote}
                  </p>
                </div>
              </div>
            </TabsPrimitive.Content>
          );
        })}
      </TabsPrimitive.Root>
    </section>
  );
}
