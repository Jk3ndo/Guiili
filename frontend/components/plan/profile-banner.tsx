"use client";

import { useState } from "react";
import { toast } from "sonner";

import {
  describeMeasurementError,
  patchMeasurementProfile,
  type MeasurementPlanDto,
  type SiteType,
} from "@/lib/api/measurement";
import { cn } from "@/lib/utils";

import { SITE_TYPE_LABEL } from "./labels";

const ALL_TYPES: SiteType[] = ["ecommerce", "lead_gen", "saas", "content", "other"];

/** Le type de site deviné est déjà appliqué : ce bandeau permet de le confirmer ou de le
 * corriger, sans jamais bloquer la suite. Il disparaît une fois confirmé. */
export function ProfileBanner({
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
  const [editing, setEditing] = useState(false);
  const [hidden, setHidden] = useState(false);
  const [selected, setSelected] = useState<SiteType[]>(plan.profile.effective_types);
  const [saving, setSaving] = useState(false);

  if (!plan.profile.needs_confirmation || hidden) return null;

  const current = plan.profile.effective_types
    .map((type) => SITE_TYPE_LABEL[type] ?? type)
    .join(", ");

  function toggle(type: SiteType) {
    setSelected((list) =>
      list.includes(type) ? list.filter((item) => item !== type) : [...list, type],
    );
  }

  async function confirm(types: SiteType[]) {
    if (types.length === 0) {
      toast.error("Choisis au moins un type de site.");
      return;
    }
    setSaving(true);
    try {
      onChanged(await patchMeasurementProfile(websiteId, { confirmed_types: types }));
      toast("Type de site confirmé", { description: "Le plan a été ajusté." });
      setEditing(false);
    } catch (error) {
      toast.error(describeMeasurementError(error));
    } finally {
      setSaving(false);
    }
  }

  return (
    <section className="space-y-3 rounded-xl border border-white/[0.08] bg-surface/40 px-5 py-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-xs text-ink-muted">
          On pense que ton site est : <span className="font-medium text-ink">{current}</span>. Le
          plan est déjà adapté.
        </p>
        {isOwner && !editing && (
          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              disabled={saving}
              onClick={() => void confirm(plan.profile.effective_types)}
              className="inline-flex h-8 items-center rounded-lg border border-white/[0.08] bg-white/[0.03] px-2.5 text-xs font-medium text-ink-muted transition-colors hover:bg-white/[0.06] hover:text-ink disabled:opacity-60"
            >
              C&apos;est bien ça
            </button>
            <button
              type="button"
              onClick={() => setEditing(true)}
              className="text-xs text-ink-faint underline hover:text-ink"
            >
              Corriger
            </button>
            <button
              type="button"
              onClick={() => setHidden(true)}
              className="text-xs text-ink-faint hover:text-ink"
            >
              Plus tard
            </button>
          </div>
        )}
      </div>
      {editing && (
        <div className="space-y-3">
          <div className="flex flex-wrap gap-2">
            {ALL_TYPES.map((type) => (
              <button
                key={type}
                type="button"
                aria-pressed={selected.includes(type)}
                onClick={() => toggle(type)}
                className={cn(
                  "inline-flex h-8 items-center rounded-lg border px-3 text-xs font-medium transition-colors",
                  selected.includes(type)
                    ? "border-ink/40 bg-white/[0.08] text-ink"
                    : "border-white/[0.08] bg-white/[0.03] text-ink-muted hover:bg-white/[0.06] hover:text-ink",
                )}
              >
                {SITE_TYPE_LABEL[type]}
              </button>
            ))}
          </div>
          <p className="text-2xs text-ink-faint">Un site peut être de plusieurs types.</p>
          <button
            type="button"
            disabled={saving}
            onClick={() => void confirm(selected)}
            className="inline-flex h-9 items-center rounded-lg bg-zinc-100 px-4 text-xs font-medium text-zinc-950 shadow-sm transition-colors hover:bg-zinc-200 disabled:opacity-60"
          >
            Confirmer
          </button>
        </div>
      )}
    </section>
  );
}
