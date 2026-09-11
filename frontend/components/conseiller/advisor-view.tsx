"use client";

import { Loader2, Sparkle } from "lucide-react";
import { useEffect, useState } from "react";
import { toast } from "sonner";

import { PageShell } from "@/components/shell/page-shell";
import {
  fetchAdvisorSettings,
  fetchThread,
  fetchThreads,
  generateBrief,
} from "@/lib/api/advisor";
import { ApiError } from "@/lib/api/client";
import type {
  AdvisorSettingsDto,
  AdvisorThreadSummaryDto,
} from "@/lib/api/dto";
import { useShell } from "@/lib/shell/shell-context";

import { BriefMarkdown } from "./brief-markdown";
import { PersonaPicker } from "./persona-picker";

function AdvisorPanel({ websiteId }: { websiteId: string }) {
  const [settings, setSettings] = useState<AdvisorSettingsDto | null>(null);
  const [threads, setThreads] = useState<AdvisorThreadSummaryDto[]>([]);
  const [content, setContent] = useState<string | null>(null);
  const [generating, setGenerating] = useState(false);

  useEffect(() => {
    let active = true;
    void (async () => {
      try {
        const [s, t] = await Promise.all([
          fetchAdvisorSettings(),
          fetchThreads(websiteId),
        ]);
        if (!active) return;
        setSettings(s);
        setThreads(t);
      } catch {
        if (active) toast.error("Impossible de charger le conseiller");
      }
    })();
    return () => {
      active = false;
    };
  }, [websiteId]);

  async function onGenerate() {
    setGenerating(true);
    setContent(null);
    try {
      const brief = await generateBrief(websiteId);
      setContent(brief.content);
      setThreads((current) => [
        {
          id: brief.thread_id,
          title: `Plan d'action — ${new Date().toISOString().slice(0, 10)}`,
          created_at: new Date().toISOString(),
          message_count: 1,
        },
        ...current,
      ]);
    } catch (error) {
      if (error instanceof ApiError && error.status === 429) {
        toast.error(error.message);
      } else if (error instanceof ApiError && error.status === 502) {
        toast.error("Le conseiller n'a pas pu répondre, réessaie dans un instant");
      } else {
        toast.error("La génération a échoué");
      }
    } finally {
      setGenerating(false);
    }
  }

  async function openThread(id: string) {
    try {
      const thread = await fetchThread(id);
      const assistant = thread.messages.find((m) => m.role === "assistant");
      setContent(assistant?.text ?? "");
    } catch {
      toast.error("Impossible d'ouvrir ce plan");
    }
  }

  return (
    <>
      {settings ? (
        <PersonaPicker
          presets={settings.presets}
          personaKey={settings.persona_key}
          customPrompt={settings.custom_prompt}
        />
      ) : null}

      <div className="flex flex-wrap items-center gap-3">
        <button
          type="button"
          onClick={() => void onGenerate()}
          disabled={generating}
          className="inline-flex h-9 items-center gap-2 rounded-lg bg-zinc-100 px-4 text-xs font-medium text-zinc-950 shadow-sm transition-colors hover:bg-zinc-200 disabled:opacity-60"
        >
          {generating ? (
            <Loader2 className="size-3.5 animate-spin" />
          ) : (
            <Sparkle className="size-3.5" />
          )}
          {generating ? "Analyse en cours… (jusqu'à 40 s)" : "Générer le plan d'action"}
        </button>
        {threads.length > 0 ? (
          <span className="text-xs text-ink-faint">
            {threads.length} plan{threads.length > 1 ? "s" : ""} généré
            {threads.length > 1 ? "s" : ""}
          </span>
        ) : null}
      </div>

      {content !== null ? (
        <article className="rounded-xl border border-white/[0.08] bg-surface/60 p-6 backdrop-blur-sm">
          <BriefMarkdown content={content} />
        </article>
      ) : null}

      {threads.length > 0 ? (
        <div className="rounded-xl border border-white/[0.08] bg-surface/30">
          <header className="border-b border-white/[0.05] px-5 py-3 text-xs text-ink-faint">
            Plans précédents
          </header>
          <ul>
            {threads.map((thread) => (
              <li
                key={thread.id}
                className="border-b border-white/[0.05] last:border-0"
              >
                <button
                  type="button"
                  onClick={() => void openThread(thread.id)}
                  className="w-full px-5 py-3 text-left text-sm text-ink-muted transition-colors hover:bg-white/[0.02] hover:text-ink"
                >
                  {thread.title}
                </button>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </>
  );
}

export function AdvisorView() {
  const { workspace } = useShell();

  return (
    <PageShell
      title="Conseiller"
      subtitle="Un plan d'action priorisé, généré à partir du dernier diagnostic du site."
    >
      {workspace.websiteId ? (
        <AdvisorPanel key={workspace.websiteId} websiteId={workspace.websiteId} />
      ) : (
        <div className="rounded-xl border border-white/[0.08] bg-surface/60 p-5 text-sm text-ink-muted backdrop-blur-sm">
          Ajoute d&apos;abord un vrai site (bouton « + » dans le sélecteur de
          projet) et lance un diagnostic : le conseiller a besoin de données
          réelles pour bâtir un plan.
        </div>
      )}
    </PageShell>
  );
}
