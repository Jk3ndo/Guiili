"use client";

import { useState } from "react";
import { toast } from "sonner";

import { saveAdvisorSettings } from "@/lib/api/advisor";
import type { AdvisorPresetDto } from "@/lib/api/dto";

const CUSTOM = "custom";
const CUSTOM_MAX = 2000;

export function PersonaPicker({
  presets,
  personaKey,
  customPrompt,
}: {
  presets: AdvisorPresetDto[];
  personaKey: string;
  customPrompt: string | null;
}) {
  const [key, setKey] = useState(personaKey);
  const [custom, setCustom] = useState(customPrompt ?? "");
  const [saving, setSaving] = useState(false);

  async function persist(nextKey: string, nextCustom: string) {
    if (nextKey === CUSTOM && !nextCustom.trim()) return;
    setSaving(true);
    try {
      await saveAdvisorSettings({
        persona_key: nextKey,
        custom_prompt: nextKey === CUSTOM ? nextCustom.trim() : null,
      });
      toast.success("Persona enregistrée");
    } catch {
      toast.error("Enregistrement impossible");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="rounded-xl border border-white/[0.08] bg-surface/60 p-5 backdrop-blur-sm">
      <label className="text-xs text-ink-faint" htmlFor="persona">
        Ton du conseiller
      </label>
      <select
        id="persona"
        value={key}
        disabled={saving}
        onChange={(event) => {
          setKey(event.target.value);
          void persist(event.target.value, custom);
        }}
        className="mt-1.5 h-9 w-full max-w-sm rounded-md border border-white/[0.08] bg-white/[0.03] px-2 text-sm text-ink focus:border-white/20 focus:outline-none"
      >
        {presets.map((preset) => (
          <option key={preset.key} value={preset.key}>
            {preset.label}
          </option>
        ))}
        <option value={CUSTOM}>Personnalisé…</option>
      </select>

      {key === CUSTOM ? (
        <textarea
          value={custom}
          maxLength={CUSTOM_MAX}
          disabled={saving}
          onChange={(event) => setCustom(event.target.value)}
          onBlur={() => void persist(CUSTOM, custom)}
          placeholder="Décris le ton et les priorités que tu veux (max 2000 caractères)."
          className="mt-3 h-28 w-full rounded-md border border-white/[0.08] bg-white/[0.03] p-2.5 text-sm text-ink-muted focus:border-white/20 focus:outline-none"
        />
      ) : null}
    </div>
  );
}
