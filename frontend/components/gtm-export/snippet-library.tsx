"use client";

import { FolderTree } from "lucide-react";
import { Tabs as TabsPrimitive } from "radix-ui";
import { useState } from "react";

import { STACK_LABEL } from "@/components/shell/stack-badge";
import type { SnippetEntryDto } from "@/lib/api/dto";
import { useSnippets } from "@/lib/api/hooks";
import { mapStack } from "@/lib/api/mappers";
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

function Header({ hint }: { hint: string }) {
  return (
    <div className="space-y-1">
      <h2 className="text-sm font-medium text-ink">
        Instrumentation du code client
      </h2>
      <p className="max-w-2xl text-xs leading-relaxed text-ink-muted">
        Snippets <span className="font-mono">dataLayer.push</span> prêts à
        coller, générés pour votre stack et l&apos;événement à suivre. {hint}
      </p>
    </div>
  );
}

function EventPills({
  event,
  onChange,
}: {
  event: GtmEventId;
  onChange: (event: GtmEventId) => void;
}) {
  return (
    <div className="flex flex-wrap gap-1.5">
      {GTM_EVENTS.map((option) => (
        <button
          key={option.id}
          type="button"
          onClick={() => onChange(option.id)}
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
  );
}

function PlacementBox({ path, note }: { path: string; note: string }) {
  return (
    <div className="flex items-start gap-2.5 rounded-lg border border-white/[0.08] bg-white/[0.02] px-3.5 py-3">
      <FolderTree className="mt-0.5 size-4 shrink-0 text-ink-faint" />
      <div className="space-y-1">
        <p className="text-xs text-ink-muted">
          Emplacement recommandé&nbsp;·{" "}
          <span className="font-mono text-ink">{path}</span>
        </p>
        <p className="text-xs leading-relaxed text-ink-muted">{note}</p>
      </div>
    </div>
  );
}

/** Snippets issus du registre backend : une stack fixe (celle détectée). */
function ApiSnippetLibrary({
  entries,
  stack,
}: {
  entries: SnippetEntryDto[];
  stack: string;
}) {
  const [event, setEvent] = useState<GtmEventId>("purchase");
  const entry = entries.find((item) => item.event === event) ?? entries[0];

  return (
    <section className="space-y-4">
      <Header
        hint={`Stack détectée : ${STACK_LABEL[mapStack(stack)]} (registre backend).`}
      />
      <EventPills event={event} onChange={setEvent} />
      {entry && (
        <div className="space-y-3">
          <CodeBlock
            code={entry.code}
            filename={`snippet.${entry.language}`}
          />
          <PlacementBox path={entry.target_path} note={entry.instructions} />
        </div>
      )}
    </section>
  );
}

/** Fallback mocké : les 3 stacks en onglets, snippets colorés côté serveur. */
function MockSnippetLibrary({
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
      <Header hint={`Stack détectée : ${detectedLabel}.`} />

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

        <div className="mt-4">
          <EventPills event={event} onChange={setEvent} />
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
              <PlacementBox path={snippet.location} note={snippet.locationNote} />
            </TabsPrimitive.Content>
          );
        })}
      </TabsPrimitive.Root>
    </section>
  );
}

export function SnippetLibrary({
  workspace,
  highlighted,
}: {
  workspace: Workspace;
  highlighted: HighlightedSnippets;
}) {
  const { snippets } = useSnippets(workspace);

  if (snippets && snippets.entries.length > 0) {
    return (
      <ApiSnippetLibrary
        entries={snippets.entries}
        stack={snippets.resolved_stack}
      />
    );
  }

  return <MockSnippetLibrary workspace={workspace} highlighted={highlighted} />;
}
