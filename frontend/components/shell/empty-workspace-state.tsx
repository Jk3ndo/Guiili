"use client";

import { Radar } from "lucide-react";
import { useState } from "react";

import { AddWebsiteDialog } from "./add-website-dialog";

/**
 * Rendu par `ShellProvider` tant que l'utilisateur connecté n'a encore aucun
 * site réel — remplace tout le shell (sidebar/topbar) le temps qu'il ajoute
 * son premier domaine, plutôt que d'afficher un sélecteur vide ou des sites
 * de démonstration qui ne lui appartiennent pas.
 */
export function EmptyWorkspaceState() {
  const [open, setOpen] = useState(false);

  return (
    <div className="flex min-h-screen items-center justify-center bg-canvas px-4">
      <div className="w-full max-w-sm space-y-4 rounded-xl border border-hairline bg-surface/60 p-6 text-center">
        <span className="mx-auto flex size-10 items-center justify-center rounded-lg border border-hairline bg-white/[0.04] text-ink">
          <Radar className="size-5" />
        </span>
        <div className="space-y-1">
          <h1 className="text-sm font-medium text-ink">Aucun site pour l&apos;instant</h1>
          <p className="text-xs text-ink-muted">
            Ajoute ton premier domaine pour lancer un diagnostic et commencer à
            suivre son marketing.
          </p>
        </div>
        <button
          type="button"
          onClick={() => setOpen(true)}
          className="inline-flex h-9 w-full items-center justify-center gap-2 rounded-lg bg-zinc-100 text-xs font-medium text-zinc-950 shadow-sm transition-colors hover:bg-zinc-200"
        >
          <Radar className="size-3.5" />
          Ajouter un site
        </button>
      </div>
      <AddWebsiteDialog open={open} onOpenChange={setOpen} />
    </div>
  );
}
