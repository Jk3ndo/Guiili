"use client";

import { Plus } from "lucide-react";
import { useState } from "react";

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import {
  CATEGORY_LABEL,
  SEVERITY_LABEL,
  type IssueCategory,
  type IssueSeverity,
} from "@/lib/mock/backlog";
import { cn } from "@/lib/utils";

export interface NewIssueDraft {
  title: string;
  category: IssueCategory;
  severity: IssueSeverity;
  note: string;
  snippet: string;
}

const CATEGORIES = Object.keys(CATEGORY_LABEL) as IssueCategory[];
const SEVERITIES = Object.keys(SEVERITY_LABEL) as IssueSeverity[];

function PillGroup<T extends string>({
  label,
  value,
  options,
  labels,
  onChange,
}: {
  label: string;
  value: T;
  options: T[];
  labels: Record<T, string>;
  onChange: (value: T) => void;
}) {
  return (
    <div className="space-y-1.5">
      <span className="text-xs font-medium text-ink">{label}</span>
      <div className="flex flex-wrap gap-1.5">
        {options.map((option) => (
          <button
            key={option}
            type="button"
            onClick={() => onChange(option)}
            className={cn(
              "rounded-lg border px-2.5 py-1 text-xs font-medium transition-colors",
              value === option
                ? "border-white/[0.14] bg-white/[0.06] text-ink"
                : "border-white/[0.08] bg-white/[0.02] text-ink-muted hover:text-ink",
            )}
          >
            {labels[option]}
          </button>
        ))}
      </div>
    </div>
  );
}

export function AddIssueDialog({
  open,
  onOpenChange,
  onCreate,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onCreate: (draft: NewIssueDraft) => void;
}) {
  const [title, setTitle] = useState("");
  const [category, setCategory] = useState<IssueCategory>("ga4");
  const [severity, setSeverity] = useState<IssueSeverity>("warning");
  const [note, setNote] = useState("");
  const [snippet, setSnippet] = useState("");

  function reset() {
    setTitle("");
    setCategory("ga4");
    setSeverity("warning");
    setNote("");
    setSnippet("");
  }

  function handleOpenChange(next: boolean) {
    if (!next) reset();
    onOpenChange(next);
  }

  function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    const trimmed = title.trim();
    if (!trimmed) return;
    onCreate({
      title: trimmed,
      category,
      severity,
      note: note.trim(),
      snippet: snippet.trim(),
    });
    reset();
    onOpenChange(false);
  }

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className="gap-0 border-white/[0.1] bg-raised p-0 sm:max-w-md">
        <DialogHeader className="gap-1 border-b border-white/[0.06] p-5 text-left">
          <DialogTitle className="text-sm font-semibold text-ink">
            Ajouter une anomalie
          </DialogTitle>
          <DialogDescription className="text-xs text-ink-muted">
            Crée un ticket manuel. Il apparaît dans la colonne « À traiter ».
          </DialogDescription>
        </DialogHeader>

        <form onSubmit={handleSubmit} className="space-y-4 p-5">
          <label className="block space-y-1.5">
            <span className="text-xs font-medium text-ink">Titre</span>
            <Input
              value={title}
              onChange={(event) => setTitle(event.target.value)}
              placeholder="Ex. Le tag GA4 purchase ne transmet pas la valeur"
              className="h-9 rounded-lg text-xs"
            />
          </label>

          <PillGroup
            label="Catégorie"
            value={category}
            options={CATEGORIES}
            labels={CATEGORY_LABEL}
            onChange={setCategory}
          />
          <PillGroup
            label="Sévérité"
            value={severity}
            options={SEVERITIES}
            labels={SEVERITY_LABEL}
            onChange={setSeverity}
          />

          <label className="block space-y-1.5">
            <span className="text-xs font-medium text-ink">
              Note <span className="text-ink-faint">— optionnel</span>
            </span>
            <textarea
              value={note}
              onChange={(event) => setNote(event.target.value)}
              rows={2}
              placeholder="Contexte, impact estimé…"
              className="w-full rounded-lg border border-input bg-transparent px-3 py-2 text-xs leading-relaxed text-ink outline-none placeholder:text-ink-faint focus-visible:border-ring"
            />
          </label>

          <label className="block space-y-1.5">
            <span className="text-xs font-medium text-ink">
              Snippet <span className="text-ink-faint">— optionnel</span>
            </span>
            <textarea
              value={snippet}
              onChange={(event) => setSnippet(event.target.value)}
              rows={4}
              spellCheck={false}
              placeholder="// correctif proposé"
              className="w-full rounded-lg border border-input bg-[#0c1119] px-3 py-2 font-mono text-xs leading-relaxed text-ink-muted outline-none placeholder:text-ink-faint focus-visible:border-ring"
            />
          </label>

          <div className="flex justify-end gap-2 pt-1">
            <button
              type="button"
              onClick={() => handleOpenChange(false)}
              className="inline-flex h-9 items-center rounded-lg border border-white/[0.08] bg-white/[0.03] px-3.5 text-xs font-medium text-ink-muted transition-colors hover:bg-white/[0.06] hover:text-ink"
            >
              Annuler
            </button>
            <button
              type="submit"
              disabled={!title.trim()}
              className="inline-flex h-9 items-center gap-1.5 rounded-lg bg-zinc-100 px-4 text-xs font-medium text-zinc-950 shadow-sm transition-colors hover:bg-zinc-200 disabled:opacity-40"
            >
              <Plus className="size-3.5" />
              Ajouter
            </button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}
