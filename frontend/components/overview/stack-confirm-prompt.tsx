"use client";

import { Layers } from "lucide-react";
import { useState } from "react";

import { StackPickerDialog } from "@/components/shell/stack-picker-dialog";
import { useShell } from "@/lib/shell/shell-context";

/** Invite à confirmer la stack quand la détection auto est restée floue. */
export function StackConfirmPrompt() {
  const { workspace } = useShell();
  const [open, setOpen] = useState(false);

  const needsConfirm =
    workspace.websiteId != null &&
    workspace.stack === "other" &&
    !workspace.stackLabel?.trim();

  if (!needsConfirm) return null;

  return (
    <>
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-white/[0.08] bg-surface/60 p-4 backdrop-blur-sm">
        <div className="flex items-start gap-2.5">
          <Layers className="mt-0.5 size-4 shrink-0 text-ink-faint" />
          <div className="space-y-0.5">
            <p className="text-xs font-medium text-ink">
              Stack technique non identifiée
            </p>
            <p className="text-2xs leading-relaxed text-ink-muted">
              La détection automatique n&apos;a rien trouvé de concluant.
              Confirme la stack pour des recommandations plus ciblées.
            </p>
          </div>
        </div>
        <button
          type="button"
          onClick={() => setOpen(true)}
          className="inline-flex h-8 shrink-0 items-center gap-1.5 rounded-lg border border-white/[0.1] bg-white/[0.04] px-3 text-2xs font-medium text-ink transition-colors hover:bg-white/[0.08]"
        >
          Confirmer la stack
        </button>
      </div>

      <StackPickerDialog
        websiteId={workspace.websiteId ?? null}
        open={open}
        onOpenChange={setOpen}
      />
    </>
  );
}
