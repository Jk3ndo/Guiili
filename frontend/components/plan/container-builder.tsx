"use client";

import { useState } from "react";
import { toast } from "sonner";

import { saveBlob } from "@/lib/api/client";
import {
  buildMeasurementContainer,
  describeMeasurementError,
  type ContainerSelection,
  type MeasurementItemDto,
  type MeasurementPlanDto,
} from "@/lib/api/measurement";

const IMPORT_STEPS =
  "Dans Google Tag Manager : Administration > Importer un conteneur > choisis le fichier > " +
  "« Nouvel espace de travail » > « Fusionner » > « Renommer les conflits » > confirme, " +
  "vérifie en mode Aperçu, puis clique sur « Envoyer » pour publier.";

function siteCodeNote(ids: string[], items: MeasurementItemDto[]): string | null {
  if (ids.length === 0) return null;
  const titles = ids
    .map((id) => items.find((item) => item.id === id)?.title ?? id)
    .join(", ");
  return `Ces événements ont aussi besoin d'un petit code dans ton site (snippet dans la ligne correspondante) : ${titles}.`;
}

/** Génère le conteneur, déclenche le téléchargement et renvoie les notes à montrer telles
 * quelles (avertissements du générateur, puis rappel des événements qui demandent du code
 * côté site). */
async function download(
  websiteId: string,
  selection: ContainerSelection,
  items: MeasurementItemDto[],
): Promise<string[]> {
  const result = await buildMeasurementContainer(websiteId, selection);
  saveBlob(
    new Blob([JSON.stringify(result.container, null, 2)], { type: "application/json" }),
    result.filename,
  );
  return [...result.warnings, siteCodeNote(result.needs_site_code, items)].filter(
    (note): note is string => note !== null,
  );
}

function Notes({ notes }: { notes: string[] }) {
  if (notes.length === 0) return null;
  return (
    <ul className="space-y-1 text-xs leading-relaxed text-warn">
      {notes.map((note, index) => (
        <li key={index}>{note}</li>
      ))}
    </ul>
  );
}

/** Palier 3 : un fichier, aucune case à cocher. */
export function StarterPackCard({
  websiteId,
  plan,
}: {
  websiteId: string;
  plan: MeasurementPlanDto;
}) {
  const [busy, setBusy] = useState(false);
  const [notes, setNotes] = useState<string[]>([]);

  async function generate() {
    setBusy(true);
    try {
      setNotes(await download(websiteId, { pack: "starter" }, plan.items));
      toast("Pack de démarrage généré", { description: IMPORT_STEPS });
    } catch (error) {
      toast.error(describeMeasurementError(error));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="space-y-3 rounded-xl border border-white/[0.08] bg-surface/60 p-5">
      <div className="space-y-1">
        <p className="text-sm font-medium text-ink">Pack de démarrage</p>
        <p className="max-w-2xl text-xs leading-relaxed text-ink-muted">
          Un seul fichier à importer dans Google Tag Manager, avec Google Analytics 4 et les
          événements essentiels pour ton type de site. Aucun choix à faire : on vérifie ensuite
          tout seul que ça marche.
        </p>
      </div>
      <button
        type="button"
        disabled={busy}
        onClick={() => void generate()}
        className="inline-flex h-9 items-center rounded-lg bg-zinc-100 px-4 text-xs font-medium text-zinc-950 shadow-sm transition-colors hover:bg-zinc-200 disabled:opacity-60"
      >
        Générer mon pack de démarrage
      </button>
      <p className="text-2xs leading-relaxed text-ink-faint">{IMPORT_STEPS}</p>
      <Notes notes={notes} />
    </section>
  );
}

/** Option avancée : choisir soi-même les lignes du conteneur. */
export function AdvancedContainer({
  websiteId,
  plan,
  selectMode,
  onToggleSelectMode,
  selectedIds,
  onSelectMissing,
  onClear,
}: {
  websiteId: string;
  plan: MeasurementPlanDto;
  selectMode: boolean;
  onToggleSelectMode: () => void;
  selectedIds: string[];
  onSelectMissing: () => void;
  onClear: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [notes, setNotes] = useState<string[]>([]);

  async function generate() {
    setBusy(true);
    try {
      setNotes(await download(websiteId, { item_ids: selectedIds }, plan.items));
      toast("Conteneur GTM généré", { description: IMPORT_STEPS });
    } catch (error) {
      toast.error(describeMeasurementError(error));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="space-y-3 rounded-xl border border-white/[0.08] bg-surface/60 p-5">
      <div className="space-y-1">
        <p className="text-sm font-medium text-ink">Conteneur GTM personnalisé</p>
        <p className="max-w-2xl text-xs leading-relaxed text-ink-muted">
          Pour aller plus loin que le pack de démarrage : choisis toi-même les lignes à inclure.
        </p>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          onClick={onToggleSelectMode}
          className="inline-flex h-8 items-center rounded-lg border border-white/[0.08] bg-white/[0.03] px-2.5 text-xs font-medium text-ink-muted transition-colors hover:bg-white/[0.06] hover:text-ink"
        >
          {selectMode ? "Terminer la sélection" : "Choisir les lignes"}
        </button>
        {selectMode && (
          <>
            <button
              type="button"
              onClick={onSelectMissing}
              className="inline-flex h-8 items-center rounded-lg border border-white/[0.08] bg-white/[0.03] px-2.5 text-xs font-medium text-ink-muted transition-colors hover:bg-white/[0.06] hover:text-ink"
            >
              Cocher les lignes manquantes
            </button>
            {selectedIds.length > 0 && (
              <button
                type="button"
                onClick={onClear}
                className="text-xs text-ink-faint underline hover:text-ink"
              >
                Tout décocher
              </button>
            )}
            <button
              type="button"
              disabled={busy || selectedIds.length === 0}
              onClick={() => void generate()}
              className="inline-flex h-9 items-center rounded-lg bg-zinc-100 px-4 text-xs font-medium text-zinc-950 shadow-sm transition-colors hover:bg-zinc-200 disabled:opacity-50"
            >
              Générer ({selectedIds.length})
            </button>
          </>
        )}
      </div>
      <Notes notes={notes} />
    </section>
  );
}
