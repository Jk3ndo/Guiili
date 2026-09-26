"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";

import { CopyButton } from "@/components/backlog/copy-button";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import {
  describeMeasurementError,
  patchMeasurementItem,
  type MeasurementItemDto,
  type MeasurementPlanDto,
} from "@/lib/api/measurement";

import { truncate } from "./format";
import { reasonLabel, stateLabel } from "./labels";

/** Les lignes « manuelles » n'ont pas d'indicateur dédié dans l'API : elles se reconnaissent à
 * leur raison (`manual_check`) ou à un marquage déjà posé (`evidence.manual_done`). */
function isManualItem(item: MeasurementItemDto): boolean {
  return item.reason === "manual_check" || item.evidence.manual_done === true;
}

function showEvidence(value: unknown): string {
  return truncate(JSON.stringify(value) ?? String(value), 300);
}

export function ItemDrawer({
  item,
  websiteId,
  isOwner,
  domain,
  onClose,
  onChanged,
}: {
  item: MeasurementItemDto | null;
  websiteId: string;
  isOwner: boolean;
  domain: string;
  onClose: () => void;
  onChanged: (plan: MeasurementPlanDto) => void;
}) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);

  async function patch(body: { dismissed?: boolean; manual_done?: boolean }) {
    if (!item) return;
    setBusy(true);
    try {
      onChanged(await patchMeasurementItem(websiteId, item.id, body));
    } catch (error) {
      toast.error(describeMeasurementError(error));
    } finally {
      setBusy(false);
    }
  }

  function askAdvisor() {
    if (!item) return;
    const prompt =
      `Sur le site ${domain}, la ligne « ${item.title} » de mon plan de mesure est ` +
      `« ${stateLabel(item)} ». Explique-moi simplement pourquoi ça compte et ce que je ` +
      `dois faire concrètement, étape par étape.`;
    router.push(`/conseiller?prompt=${encodeURIComponent(prompt)}`);
  }

  const reason = item && !item.done ? reasonLabel(item.reason) : null;

  return (
    <Sheet open={item !== null} onOpenChange={(open) => !open && onClose()}>
      <SheetContent side="right" className="w-full overflow-y-auto sm:max-w-lg">
        {item && (
          <>
            <SheetHeader>
              <SheetTitle className="text-base text-ink">{item.title}</SheetTitle>
              <SheetDescription className="text-xs text-ink-muted">
                {stateLabel(item)}
                {reason ? ` — ${reason}` : ""}
              </SheetDescription>
            </SheetHeader>

            <div className="space-y-6 px-4 pb-6">
              <section className="space-y-1">
                <h3 className="text-xs font-medium text-ink">Pourquoi ça compte</h3>
                <p className="text-xs leading-relaxed text-ink-muted">{item.why}</p>
              </section>

              {Object.keys(item.evidence).length > 0 && (
                <section className="space-y-1">
                  <h3 className="text-xs font-medium text-ink">Ce qu&apos;on a constaté</h3>
                  <dl className="space-y-1 rounded-lg border border-hairline bg-white/[0.02] p-3 font-mono text-2xs text-ink-muted">
                    {Object.entries(item.evidence).map(([key, value]) => (
                      <div key={key} className="flex gap-2">
                        <dt className="shrink-0 text-ink-faint">{key}</dt>
                        <dd className="min-w-0 break-words">{showEvidence(value)}</dd>
                      </div>
                    ))}
                  </dl>
                </section>
              )}

              {item.actions.includes("guide") && item.guide.length > 0 && (
                <section className="space-y-2">
                  <h3 className="text-xs font-medium text-ink">Comment faire</h3>
                  <ol className="list-decimal space-y-1.5 pl-4 text-xs leading-relaxed text-ink-muted">
                    {item.guide.map((step, index) => (
                      <li key={index}>{step}</li>
                    ))}
                  </ol>
                </section>
              )}

              {item.snippet && (
                <section className="space-y-2">
                  <div className="flex items-center justify-between">
                    <h3 className="text-xs font-medium text-ink">Snippet</h3>
                    <CopyButton text={item.snippet.code} />
                  </div>
                  <p className="text-2xs text-ink-faint">
                    Fichier suggéré : {item.snippet.target_path}
                  </p>
                  <pre className="max-h-72 overflow-auto rounded-lg border border-hairline bg-white/[0.02] p-3 font-mono text-2xs leading-relaxed text-ink-muted">
                    {item.snippet.code}
                  </pre>
                  <p className="text-2xs leading-relaxed text-ink-faint">
                    {item.snippet.instructions}
                  </p>
                </section>
              )}

              <div className="flex flex-wrap gap-2 border-t border-white/[0.06] pt-4">
                {item.actions.includes("advisor") && (
                  <button
                    type="button"
                    onClick={askAdvisor}
                    className="inline-flex h-8 items-center rounded-lg border border-white/[0.08] bg-white/[0.03] px-2.5 text-xs font-medium text-ink-muted transition-colors hover:bg-white/[0.06] hover:text-ink"
                  >
                    Demander au conseiller
                  </button>
                )}
                {item.actions.includes("pr") && (
                  <button
                    type="button"
                    disabled
                    className="inline-flex h-8 items-center rounded-lg border border-white/[0.08] px-2.5 text-xs text-ink-faint opacity-60"
                  >
                    Ouvrir une PR (bientôt)
                  </button>
                )}
                {isOwner && isManualItem(item) && (
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => void patch({ manual_done: !item.done })}
                    className="inline-flex h-8 items-center rounded-lg border border-white/[0.08] bg-white/[0.03] px-2.5 text-xs font-medium text-ink-muted transition-colors hover:bg-white/[0.06] hover:text-ink disabled:opacity-60"
                  >
                    {item.done ? "Marquer comme à refaire" : "Marquer comme fait"}
                  </button>
                )}
                {isOwner && (
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => void patch({ dismissed: item.state !== "dismissed" })}
                    className="inline-flex h-8 items-center rounded-lg border border-white/[0.08] px-2.5 text-xs text-ink-faint transition-colors hover:text-ink disabled:opacity-60"
                  >
                    {item.state === "dismissed" ? "Rétablir cette ligne" : "Écarter cette ligne"}
                  </button>
                )}
              </div>
            </div>
          </>
        )}
      </SheetContent>
    </Sheet>
  );
}
