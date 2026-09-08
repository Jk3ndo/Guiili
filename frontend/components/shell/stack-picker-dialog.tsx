"use client";

import { Check, Loader2, ShieldAlert } from "lucide-react";
import { useEffect, useState } from "react";
import { toast } from "sonner";

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import type { StackGuessDto } from "@/lib/api/dto";
import { mapStack } from "@/lib/api/mappers";
import {
  fetchStackHint,
  redetectStack,
  setWebsiteStack,
  stackLabelOf,
  STACK_PRESETS,
} from "@/lib/api/websites";
import { useShell } from "@/lib/shell/shell-context";
import { cn } from "@/lib/utils";

const CUSTOM = "__custom__";

export function StackPickerDialog({
  websiteId,
  open,
  onOpenChange,
}: {
  websiteId: string | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const { updateWorkspace } = useShell();
  const [loading, setLoading] = useState(true);
  const [detected, setDetected] = useState<string | null>(null);
  const [candidates, setCandidates] = useState<StackGuessDto[]>([]);
  const [sslBlocked, setSslBlocked] = useState(false);
  const [choice, setChoice] = useState<string>("");
  const [custom, setCustom] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!open || !websiteId) return;
    let active = true;
    void (async () => {
      setLoading(true);
      try {
        const hint = await fetchStackHint(websiteId);
        if (!active) return;
        setDetected(hint.detected_stack);
        setCandidates(hint.candidates);
        setSslBlocked(hint.error === "ssl_verification_failed");
        setChoice(hint.stack_label ?? hint.candidates[0]?.label ?? CUSTOM);
        setCustom(hint.stack_label ?? "");
      } catch {
        if (active) setCandidates([]);
      } finally {
        if (active) setLoading(false);
      }
    })();
    return () => {
      active = false;
    };
  }, [open, websiteId]);

  async function probeInsecure() {
    if (!websiteId) return;
    setBusy(true);
    try {
      const result = await redetectStack(websiteId, true);
      setDetected(result.detected_stack);
      setCandidates(result.detection.candidates);
      setSslBlocked(false);
      setChoice(result.detection.candidates[0]?.label ?? CUSTOM);
      updateWorkspace(websiteId, { stack: mapStack(result.detected_stack) });
    } catch {
      toast.error("Le site reste injoignable.");
    } finally {
      setBusy(false);
    }
  }

  async function confirm() {
    if (!websiteId) return;
    const label = (choice === CUSTOM ? custom : choice).trim();
    if (!label) return;
    setBusy(true);
    try {
      await setWebsiteStack(websiteId, label);
      updateWorkspace(websiteId, { stackLabel: label });
      toast.success("Stack enregistrée", { description: label });
      onOpenChange(false);
    } catch {
      toast.error("Enregistrement impossible.");
    } finally {
      setBusy(false);
    }
  }

  const detectedLabel =
    detected && !["generic", "unknown"].includes(detected)
      ? stackLabelOf(detected)
      : null;

  return (
    <Dialog open={open} onOpenChange={busy ? undefined : onOpenChange}>
      <DialogContent className="gap-0 border-white/[0.1] bg-raised p-0 sm:max-w-md">
        <DialogHeader className="gap-1 border-b border-white/[0.06] p-5 text-left">
          <DialogTitle className="text-sm font-semibold text-ink">
            Confirmer la stack
          </DialogTitle>
          <DialogDescription className="text-xs text-ink-muted">
            {detectedLabel
              ? `Détecté automatiquement : ${detectedLabel}. Ajuste si besoin.`
              : "La stack n'a pas pu être identifiée avec certitude — voici nos pistes."}
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4 p-5">
          {sslBlocked && (
            <div className="space-y-2 rounded-lg border border-warn/30 bg-warn/5 p-3">
              <p className="flex items-center gap-1.5 text-xs font-medium text-warn">
                <ShieldAlert className="size-3.5" />
                Certificat HTTPS non vérifié
              </p>
              <p className="text-2xs leading-relaxed text-ink-muted">
                Le site n&apos;a pas pu être sondé. Tu peux réessayer en
                ignorant les erreurs de certificat (le contenu ne sera pas
                authentifié).
              </p>
              <button
                type="button"
                onClick={probeInsecure}
                disabled={busy}
                className="inline-flex h-8 items-center gap-1.5 rounded-md border border-white/[0.1] bg-white/[0.04] px-3 text-2xs font-medium text-ink transition-colors hover:bg-white/[0.08] disabled:opacity-40"
              >
                {busy ? (
                  <Loader2 className="size-3.5 animate-spin" />
                ) : (
                  <ShieldAlert className="size-3.5" />
                )}
                Sonder quand même
              </button>
            </div>
          )}

          {loading ? (
            <p className="py-4 text-center text-xs text-ink-faint">Analyse…</p>
          ) : (
            <fieldset className="space-y-1.5">
              {candidates.map((guess) => (
                <label
                  key={guess.label}
                  className={cn(
                    "flex cursor-pointer items-start gap-2.5 rounded-lg border p-2.5 transition-colors",
                    choice === guess.label
                      ? "border-white/[0.16] bg-white/[0.05]"
                      : "border-white/[0.06] hover:bg-white/[0.02]",
                  )}
                >
                  <input
                    type="radio"
                    name="stack"
                    checked={choice === guess.label}
                    onChange={() => setChoice(guess.label)}
                    className="mt-0.5 accent-zinc-200"
                  />
                  <span className="min-w-0">
                    <span className="block text-xs font-medium text-ink">
                      {guess.label}
                    </span>
                    <span className="block text-2xs leading-relaxed text-ink-faint">
                      {guess.reason}
                    </span>
                  </span>
                </label>
              ))}

              <label
                className={cn(
                  "flex cursor-pointer items-center gap-2.5 rounded-lg border p-2.5 transition-colors",
                  choice === CUSTOM
                    ? "border-white/[0.16] bg-white/[0.05]"
                    : "border-white/[0.06] hover:bg-white/[0.02]",
                )}
              >
                <input
                  type="radio"
                  name="stack"
                  checked={choice === CUSTOM}
                  onChange={() => setChoice(CUSTOM)}
                  className="accent-zinc-200"
                />
                <span className="flex-1 text-xs font-medium text-ink">
                  Choisir / saisir
                </span>
              </label>

              {choice === CUSTOM && (
                <div className="space-y-2 pt-1 pl-7">
                  <select
                    value={STACK_PRESETS.includes(custom) ? custom : ""}
                    onChange={(event) => setCustom(event.target.value)}
                    className="h-8 w-full rounded-md border border-white/[0.08] bg-white/[0.03] px-2 text-xs text-ink-muted focus:border-white/20 focus:outline-none"
                  >
                    <option value="">— Liste des stacks —</option>
                    {STACK_PRESETS.map((preset) => (
                      <option key={preset} value={preset}>
                        {preset}
                      </option>
                    ))}
                  </select>
                  <Input
                    value={custom}
                    onChange={(event) => setCustom(event.target.value)}
                    placeholder="… ou saisir librement (ex. Phoenix / LiveView)"
                    className="h-8 rounded-md text-xs"
                  />
                </div>
              )}
            </fieldset>
          )}

          <div className="flex justify-end gap-2 pt-1">
            <button
              type="button"
              onClick={() => onOpenChange(false)}
              disabled={busy}
              className="inline-flex h-9 items-center rounded-lg border border-white/[0.08] bg-white/[0.03] px-3.5 text-xs font-medium text-ink-muted transition-colors hover:bg-white/[0.06] hover:text-ink disabled:opacity-40"
            >
              Annuler
            </button>
            <button
              type="button"
              onClick={confirm}
              disabled={busy || !(choice === CUSTOM ? custom.trim() : choice)}
              className="inline-flex h-9 items-center gap-1.5 rounded-lg bg-zinc-100 px-4 text-xs font-medium text-zinc-950 shadow-sm transition-colors hover:bg-zinc-200 disabled:opacity-40"
            >
              {busy ? (
                <Loader2 className="size-3.5 animate-spin" />
              ) : (
                <Check className="size-3.5" />
              )}
              Enregistrer
            </button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
