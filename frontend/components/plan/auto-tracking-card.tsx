"use client";

import { Loader2 } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import {
  describeScheduleError,
  fetchSchedules,
  updateSchedule,
  type ScheduleDto,
  type ScheduleFrequency,
  type SchedulesDto,
} from "@/lib/api/schedules";

import { formatDateTime } from "./format";

// Pas de `focus:outline-none` : le focus clavier visible global (`:focus-visible`) reste actif.
const SELECT =
  "h-8 rounded-lg border border-white/[0.08] bg-white/[0.03] px-2 text-xs text-ink focus:border-ink/40 disabled:opacity-60";
const SECONDARY =
  "inline-flex h-8 items-center rounded-lg border border-white/[0.08] bg-white/[0.03] px-3 text-xs font-medium text-ink-muted transition-colors hover:bg-white/[0.06] hover:text-ink";

interface SchedulePatch {
  frequency: ScheduleFrequency;
  enabled: boolean;
}

function statusOf(schedule: ScheduleDto): { label: string; tone: string } {
  if (!schedule.enabled) return { label: "En pause", tone: "text-ink-faint" };
  switch (schedule.last_status) {
    case "succeeded":
      return { label: "À jour", tone: "text-ok" };
    case "failed":
      return { label: "En échec", tone: "text-danger" };
    case "skipped":
      return { label: "En attente", tone: "text-warn" };
    case "queued":
    case "running":
      return { label: "En cours", tone: "text-ink-muted" };
    default:
      return { label: "Pas encore exécuté", tone: "text-ink-faint" };
  }
}

function ScheduleRow({
  schedule,
  labels,
  canEdit,
  saving,
  onPatch,
}: {
  schedule: ScheduleDto;
  labels: Record<ScheduleFrequency, string>;
  canEdit: boolean;
  saving: boolean;
  onPatch: (patch: SchedulePatch) => void;
}) {
  const status = statusOf(schedule);
  const lastRun = formatDateTime(schedule.last_run_at);
  const nextRun = schedule.enabled ? formatDateTime(schedule.next_due_at) : null;
  // `last_error` est le texte français décidé par le backend (jamais un code brut).
  const showError = schedule.last_error !== null && schedule.last_status !== "succeeded";

  return (
    <li className="flex flex-wrap items-start justify-between gap-3 px-5 py-3">
      <div className="min-w-0 space-y-1">
        <p className="text-sm text-ink">{schedule.label}</p>
        <p className="text-2xs text-ink-faint">
          <span className={status.tone}>{status.label}</span>
          {lastRun ? ` · dernier passage le ${lastRun}` : ""}
          {nextRun ? ` · prochain vers le ${nextRun}` : ""}
        </p>
        {showError && <p className="text-2xs text-ink-muted">{schedule.last_error}</p>}
      </div>
      <div className="flex items-center gap-3">
        {saving && <Loader2 className="size-3.5 animate-spin text-ink-muted" aria-hidden />}
        <select
          aria-label={`Fréquence : ${schedule.label}`}
          className={SELECT}
          value={schedule.frequency}
          disabled={!canEdit || saving}
          onChange={(event) =>
            onPatch({
              frequency: event.target.value as ScheduleFrequency,
              enabled: schedule.enabled,
            })
          }
        >
          {schedule.allowed_frequencies.map((frequency) => (
            <option key={frequency} value={frequency}>
              {labels[frequency] ?? frequency}
            </option>
          ))}
        </select>
        <label className="flex items-center gap-1.5 text-xs text-ink-muted">
          <input
            type="checkbox"
            className="size-3.5 accent-zinc-200"
            checked={schedule.enabled}
            disabled={!canEdit || saving}
            onChange={(event) =>
              onPatch({ frequency: schedule.frequency, enabled: event.target.checked })
            }
          />
          Actif
        </label>
      </div>
    </li>
  );
}

export function AutoTrackingCard({ websiteId }: { websiteId: string }) {
  const [data, setData] = useState<SchedulesDto | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [savingKind, setSavingKind] = useState<string | null>(null);
  // Incrémenté par « Réessayer » : relance le chargement sans appeler setState dans l'effet.
  const [attempt, setAttempt] = useState(0);
  // Numéro du chargement en cours : une réponse arrivée après un changement de site est ignorée.
  const runId = useRef(0);

  useEffect(() => {
    const run = ++runId.current;
    fetchSchedules(websiteId)
      .then((next) => {
        if (runId.current !== run) return;
        setData(next);
        setError(null);
      })
      .catch((err: unknown) => {
        if (runId.current === run) setError(describeScheduleError(err));
      });
    return () => {
      runId.current += 1;
    };
  }, [websiteId, attempt]);

  async function change(schedule: ScheduleDto, patch: SchedulePatch) {
    setSavingKind(schedule.kind);
    try {
      setData(await updateSchedule(websiteId, { kind: schedule.kind, ...patch }));
      toast("Suivi automatique mis à jour");
    } catch (err) {
      toast.error(describeScheduleError(err));
    } finally {
      setSavingKind(null);
    }
  }

  return (
    <section className="rounded-xl border border-white/[0.08] bg-surface/60">
      <div className="space-y-1 p-5 pb-3">
        <p className="text-sm font-medium text-ink">Suivi automatique</p>
        <p className="max-w-2xl text-xs leading-relaxed text-ink-muted">
          On relève tes données et on revérifie ton site tout seuls, à la fréquence choisie.
          Les sources Google et les Core Web Vitals sont relevés au plus toutes les 8 heures
          (quotas de Google).
        </p>
      </div>

      {data === null && error === null && (
        <p className="flex items-center gap-2 px-5 pb-5 text-xs text-ink-muted" role="status">
          <Loader2 className="size-3.5 animate-spin" />
          Chargement du suivi automatique…
        </p>
      )}

      {data === null && error !== null && (
        <div className="flex flex-wrap items-center gap-3 px-5 pb-5">
          <p className="text-xs text-ink-muted">Impossible de charger le suivi automatique : {error}</p>
          <button type="button" onClick={() => {
              setError(null);
              setAttempt((value) => value + 1);
            }}
            className={SECONDARY}
          >
            Réessayer
          </button>
        </div>
      )}

      {data !== null && (
        <>
          <ul className="divide-y divide-white/[0.06] border-t border-white/[0.06]">
            {data.schedules.map((schedule) => (
              <ScheduleRow
                key={schedule.kind}
                schedule={schedule}
                labels={data.frequency_labels}
                canEdit={data.can_edit}
                saving={savingKind === schedule.kind}
                onPatch={(patch) => void change(schedule, patch)}
              />
            ))}
          </ul>
          {!data.can_edit && (
            <p className="border-t border-white/[0.06] px-5 py-3 text-2xs text-ink-faint">
              Seul le propriétaire du workspace peut modifier le suivi automatique.
            </p>
          )}
        </>
      )}
    </section>
  );
}
