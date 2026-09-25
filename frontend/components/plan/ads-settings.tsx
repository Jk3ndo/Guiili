"use client";

import { useState } from "react";
import { toast } from "sonner";

import {
  describeMeasurementError,
  patchMeasurementProfile,
  type MeasurementPlanDto,
} from "@/lib/api/measurement";

const INPUT =
  "h-9 w-full rounded-lg border border-white/[0.08] bg-white/[0.03] px-3 text-xs text-ink placeholder:text-ink-faint focus:border-ink/40 focus:outline-none disabled:opacity-60";
const SECONDARY =
  "inline-flex h-9 items-center rounded-lg border border-white/[0.08] bg-white/[0.03] px-3.5 text-xs font-medium text-ink-muted transition-colors hover:bg-white/[0.06] hover:text-ink disabled:opacity-60";

export function AdsSettings({
  websiteId,
  plan,
  isOwner,
  onChanged,
}: {
  websiteId: string;
  plan: MeasurementPlanDto;
  isOwner: boolean;
  onChanged: (plan: MeasurementPlanDto) => void;
}) {
  const params = plan.profile.params;
  const usesAds = params.uses_google_ads === true;
  const [convId, setConvId] = useState(params.ads_conversion_id ?? "");
  const [label, setLabel] = useState(params.ads_conversion_label ?? "");
  const [saving, setSaving] = useState(false);

  async function patch(body: Parameters<typeof patchMeasurementProfile>[1], done: string) {
    setSaving(true);
    try {
      onChanged(await patchMeasurementProfile(websiteId, body));
      toast(done);
    } catch (error) {
      toast.error(describeMeasurementError(error));
    } finally {
      setSaving(false);
    }
  }

  if (!usesAds) {
    return (
      <section className="space-y-3 rounded-xl border border-white/[0.08] bg-surface/60 p-5">
        <div className="space-y-1">
          <p className="text-sm font-medium text-ink">Fais-tu de la publicité Google Ads ?</p>
          <p className="max-w-2xl text-xs leading-relaxed text-ink-muted">
            Si oui, on ajoute au plan les vérifications de conversion, le lien GA4 - Ads et le
            Conversion Linker. Sinon, rien à faire : cette partie reste masquée.
          </p>
        </div>
        {isOwner ? (
          <button
            type="button"
            disabled={saving}
            onClick={() => void patch({ uses_google_ads: true }, "Publicité ajoutée au plan")}
            className={SECONDARY}
          >
            Oui, j&apos;en fais
          </button>
        ) : (
          <p className="text-xs text-ink-faint">Seul le propriétaire peut modifier ce réglage.</p>
        )}
      </section>
    );
  }

  return (
    <section className="space-y-3 rounded-xl border border-white/[0.08] bg-surface/60 p-5">
      <div className="space-y-1">
        <p className="text-sm font-medium text-ink">Réglages Google Ads</p>
        <p className="max-w-2xl text-xs leading-relaxed text-ink-muted">
          Renseigne l&apos;ID et le libellé de ta conversion (Google Ads &gt; Objectifs &gt;
          Conversions) pour les inclure dans un conteneur GTM personnalisé.
        </p>
      </div>
      <div className="grid gap-3 sm:grid-cols-2">
        <input
          className={INPUT}
          aria-label="ID de conversion Google Ads"
          placeholder="ID de conversion (AW-123456789)"
          value={convId}
          disabled={!isOwner}
          onChange={(event) => setConvId(event.target.value)}
        />
        <input
          className={INPUT}
          aria-label="Libellé de conversion Google Ads"
          placeholder="Libellé de conversion"
          value={label}
          disabled={!isOwner}
          onChange={(event) => setLabel(event.target.value)}
        />
      </div>
      {isOwner ? (
        <div className="flex flex-wrap items-center gap-3">
          <button
            type="button"
            disabled={saving}
            onClick={() =>
              void patch(
                {
                  ads_conversion_id: convId.trim() || null,
                  ads_conversion_label: label.trim() || null,
                },
                "Réglages Ads enregistrés",
              )
            }
            className={SECONDARY}
          >
            Enregistrer
          </button>
          <button
            type="button"
            disabled={saving}
            onClick={() => void patch({ uses_google_ads: false }, "Publicité retirée du plan")}
            className="text-xs text-ink-faint underline hover:text-ink disabled:opacity-60"
          >
            Je ne fais plus de publicité
          </button>
        </div>
      ) : (
        <p className="text-xs text-ink-faint">Seul le propriétaire peut modifier ces réglages.</p>
      )}
    </section>
  );
}
