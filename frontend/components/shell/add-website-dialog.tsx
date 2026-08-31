"use client";

import { Loader2, Radar } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { ApiError } from "@/lib/api/client";
import { createWebsite } from "@/lib/api/websites";
import { useShell } from "@/lib/shell/shell-context";

export function AddWebsiteDialog({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const { addWorkspace } = useShell();
  const router = useRouter();
  const [name, setName] = useState("");
  const [domain, setDomain] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function handleOpenChange(next: boolean) {
    if (busy) return;
    if (!next) {
      setName("");
      setDomain("");
      setError(null);
    }
    onOpenChange(next);
  }

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    if (busy || !name.trim() || !domain.trim()) return;
    setBusy(true);
    setError(null);
    try {
      const { workspace, detectedStackLabel } = await createWebsite({
        name: name.trim(),
        domain: domain.trim(),
      });
      toast(`${workspace.name} ajouté`, {
        description: `${detectedStackLabel} détecté · premier diagnostic exécuté.`,
      });
      addWorkspace(workspace);
      onOpenChange(false);
      setName("");
      setDomain("");
      router.push("/overview");
    } catch (cause) {
      setError(
        cause instanceof ApiError
          ? cause.message
          : "Impossible d'ajouter ce site pour le moment.",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className="gap-0 border-white/[0.1] bg-raised p-0 sm:max-w-md">
        <DialogHeader className="gap-1 border-b border-white/[0.06] p-5 text-left">
          <DialogTitle className="text-sm font-semibold text-ink">
            Ajouter un domaine
          </DialogTitle>
          <DialogDescription className="text-xs text-ink-muted">
            La stack technique est détectée et un premier diagnostic est lancé
            immédiatement.
          </DialogDescription>
        </DialogHeader>

        <form onSubmit={handleSubmit} className="space-y-4 p-5">
          <label className="block space-y-1.5">
            <span className="text-xs font-medium text-ink">Nom du projet</span>
            <Input
              value={name}
              onChange={(event) => setName(event.target.value)}
              placeholder="Ex. Mon E-commerce"
              className="h-9 rounded-lg text-xs"
              autoFocus
            />
          </label>

          <label className="block space-y-1.5">
            <span className="text-xs font-medium text-ink">Domaine ou URL</span>
            <Input
              value={domain}
              onChange={(event) => setDomain(event.target.value)}
              placeholder="monsite.fr ou https://monsite.fr"
              className="h-9 rounded-lg font-mono text-xs"
              spellCheck={false}
              autoCapitalize="off"
            />
          </label>

          {error && (
            <p className="rounded-lg border border-danger/30 bg-danger/5 px-3 py-2 text-xs text-danger">
              {error}
            </p>
          )}

          <div className="flex justify-end gap-2 pt-1">
            <button
              type="button"
              onClick={() => handleOpenChange(false)}
              disabled={busy}
              className="inline-flex h-9 items-center rounded-lg border border-white/[0.08] bg-white/[0.03] px-3.5 text-xs font-medium text-ink-muted transition-colors hover:bg-white/[0.06] hover:text-ink disabled:opacity-40"
            >
              Annuler
            </button>
            <button
              type="submit"
              disabled={busy || !name.trim() || !domain.trim()}
              className="inline-flex h-9 items-center gap-1.5 rounded-lg bg-zinc-100 px-4 text-xs font-medium text-zinc-950 shadow-sm transition-colors hover:bg-zinc-200 disabled:opacity-40"
            >
              {busy ? (
                <Loader2 className="size-3.5 animate-spin" />
              ) : (
                <Radar className="size-3.5" />
              )}
              {busy ? "Diagnostic en cours…" : "Ajouter et diagnostiquer"}
            </button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}
