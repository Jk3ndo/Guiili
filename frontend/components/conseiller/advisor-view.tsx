"use client";

import { Archive, Loader2, Sparkle } from "lucide-react";
import { useEffect, useState, type MouseEvent } from "react";
import { toast } from "sonner";

import { PageShell } from "@/components/shell/page-shell";
import {
  archiveThread,
  fetchAdvisorSettings,
  fetchThread,
  fetchThreads,
  generateBrief,
  streamChatMessage,
} from "@/lib/api/advisor";
import { ApiError } from "@/lib/api/client";
import type {
  AdvisorMessageDto,
  AdvisorSettingsDto,
  AdvisorThreadSummaryDto,
} from "@/lib/api/dto";
import { useShell } from "@/lib/shell/shell-context";

import { BriefMarkdown } from "./brief-markdown";
import { PersonaPicker } from "./persona-picker";
import { ToolChip } from "./tool-chip";

interface ChatMessage {
  role: "user" | "assistant";
  text: string;
  tools: string[];
}

/**
 * Derive les bulles affichables depuis les messages stockes : les tours
 * tool_use / tool_result n'ont pas de bulle propre, leurs noms d'outils sont
 * rattaches a la reponse assistant qui suit.
 */
function deriveChatMessages(messages: AdvisorMessageDto[]): ChatMessage[] {
  const out: ChatMessage[] = [];
  let pendingTools: string[] = [];
  for (const m of messages) {
    const toolUses = m.blocks.filter((b) => b.type === "tool_use");
    if (toolUses.length > 0) {
      pendingTools = [...pendingTools, ...toolUses.map((b) => String(b.name))];
      continue;
    }
    if (m.blocks.some((b) => b.type === "tool_result")) continue;
    if (!m.text.trim()) continue;
    out.push({ role: m.role, text: m.text, tools: pendingTools });
    pendingTools = [];
  }
  return out;
}

function AdvisorPanel({ websiteId }: { websiteId: string }) {
  const [settings, setSettings] = useState<AdvisorSettingsDto | null>(null);
  const [threads, setThreads] = useState<AdvisorThreadSummaryDto[]>([]);
  const [activeThreadId, setActiveThreadId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [chatInput, setChatInput] = useState("");
  const [generating, setGenerating] = useState(false);
  const [sending, setSending] = useState(false);

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
    try {
      const brief = await generateBrief(websiteId);
      setActiveThreadId(brief.thread_id);
      setMessages([{ role: "assistant", text: brief.content, tools: [] }]);
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
      setActiveThreadId(thread.id);
      setMessages(deriveChatMessages(thread.messages));
    } catch {
      toast.error("Impossible d'ouvrir ce plan");
    }
  }

  async function onArchive(id: string, event: MouseEvent) {
    event.stopPropagation();
    try {
      await archiveThread(id);
      setThreads((current) => current.filter((t) => t.id !== id));
      if (activeThreadId === id) {
        setActiveThreadId(null);
        setMessages([]);
      }
      toast.success("Plan archivé");
    } catch {
      toast.error("Impossible d'archiver ce plan");
    }
  }

  async function onSend() {
    const text = chatInput.trim();
    if (!text || !activeThreadId || sending) return;
    setChatInput("");
    setSending(true);
    setMessages((current) => [
      ...current,
      { role: "user", text, tools: [] },
      { role: "assistant", text: "", tools: [] },
    ]);
    try {
      for await (const event of streamChatMessage(activeThreadId, text)) {
        if (event.kind === "token") {
          setMessages((current) => {
            const next = [...current];
            const last = next[next.length - 1];
            next[next.length - 1] = { ...last, text: last.text + event.text };
            return next;
          });
        } else if (event.kind === "tool_call") {
          setMessages((current) => {
            const next = [...current];
            const last = next[next.length - 1];
            next[next.length - 1] = { ...last, tools: [...last.tools, event.tool] };
            return next;
          });
        } else if (event.kind === "error") {
          toast.error(event.text);
        }
      }
    } catch {
      toast.error("Le conseiller est injoignable");
    } finally {
      setSending(false);
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

      {messages.length > 0 ? (
        <div className="space-y-4">
          {messages.map((m, i) => (
            <article
              key={i}
              className={
                m.role === "user"
                  ? "ml-auto max-w-xl rounded-xl border border-white/[0.08] bg-white/[0.03] p-4"
                  : "rounded-xl border border-white/[0.08] bg-surface/60 p-6 backdrop-blur-sm"
              }
            >
              {m.tools.length > 0 ? (
                <div className="mb-3 flex flex-wrap gap-1.5">
                  {m.tools.map((tool, idx) => (
                    <ToolChip key={`${tool}-${idx}`} tool={tool} />
                  ))}
                </div>
              ) : null}
              {m.role === "assistant" ? (
                <BriefMarkdown content={m.text} />
              ) : (
                <p className="text-sm text-ink">{m.text}</p>
              )}
            </article>
          ))}
        </div>
      ) : null}

      {activeThreadId ? (
        <div className="flex items-end gap-2">
          <textarea
            value={chatInput}
            onChange={(event) => setChatInput(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault();
                void onSend();
              }
            }}
            disabled={sending}
            placeholder="Pose une question sur ce site…"
            className="h-11 flex-1 resize-none rounded-lg border border-white/[0.08] bg-white/[0.03] p-2.5 text-sm text-ink placeholder:text-ink-faint focus:border-white/20 focus:outline-none disabled:opacity-60"
          />
          <button
            type="button"
            onClick={() => void onSend()}
            disabled={sending || !chatInput.trim()}
            className="inline-flex h-9 items-center rounded-lg bg-zinc-100 px-4 text-xs font-medium text-zinc-950 shadow-sm transition-colors hover:bg-zinc-200 disabled:opacity-60"
          >
            Envoyer
          </button>
        </div>
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
                className="group flex items-center border-b border-white/[0.05] last:border-0"
              >
                <button
                  type="button"
                  onClick={() => void openThread(thread.id)}
                  className="flex-1 px-5 py-3 text-left text-sm text-ink-muted transition-colors hover:bg-white/[0.02] hover:text-ink"
                >
                  {thread.title}
                </button>
                <button
                  type="button"
                  onClick={(event) => void onArchive(thread.id, event)}
                  title="Archiver ce plan"
                  aria-label="Archiver ce plan"
                  className="mr-3 rounded-md p-1.5 text-ink-faint opacity-0 transition-opacity hover:text-ink group-hover:opacity-100"
                >
                  <Archive className="size-3.5" />
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
