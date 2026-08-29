"use client";

import { Plug, RotateCw } from "lucide-react";
import { toast } from "sonner";

import { relativeHours } from "@/lib/format";
import type { GoogleIdentity } from "@/lib/mock/connections";
import { cn } from "@/lib/utils";

import { GoogleGlyph } from "./google-glyph";

export function IdentityCard({ identity }: { identity: GoogleIdentity }) {
  const active = identity.status === "active";

  return (
    <div className="rounded-xl border border-white/[0.08] bg-surface/60 p-5 backdrop-blur-sm">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex items-start gap-3">
          <span className="mt-0.5 flex size-8 shrink-0 items-center justify-center rounded-lg border border-white/[0.08] bg-white/[0.03] text-ink-muted">
            <GoogleGlyph className="size-4" />
          </span>
          <div className="space-y-0.5">
            <p className="text-sm font-medium text-ink">{identity.email}</p>
            <p className="text-xs text-ink-faint">{identity.role}</p>
          </div>
        </div>

        <button
          type="button"
          onClick={() =>
            active
              ? toast("Compte déconnecté", {
                  description: `${identity.email} — accès Google révoqué (simulation).`,
                })
              : toast("Ré-authentification requise", {
                  description: `Ouverture du consentement Google pour ${identity.email}.`,
                })
          }
          className={cn(
            "inline-flex h-8 shrink-0 items-center gap-1.5 rounded-lg border px-2.5 text-xs font-medium shadow-sm transition-colors",
            active
              ? "border-white/[0.08] bg-white/[0.03] text-ink-muted hover:bg-white/[0.06] hover:text-ink"
              : "border-warn/40 bg-warn/10 text-warn hover:bg-warn/15",
          )}
        >
          {active ? (
            <>
              <Plug className="size-3.5" />
              Déconnecter
            </>
          ) : (
            <>
              <RotateCw className="size-3.5" />
              Re-synchroniser
            </>
          )}
        </button>
      </div>

      <div className="mt-4 flex flex-wrap items-center gap-1.5">
        {identity.scopes.map((scope) => (
          <span
            key={scope}
            className="inline-flex h-[18px] items-center rounded border border-hairline bg-white/[0.03] px-1.5 font-mono text-2xs text-ink-muted"
          >
            {scope}
          </span>
        ))}
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-x-2 gap-y-1 border-t border-white/[0.06] pt-3 text-xs">
        <span className="flex items-center gap-2 font-medium">
          <span
            className={cn(
              "size-1.5 shrink-0 rounded-full",
              active ? "bg-ok" : "bg-warn",
            )}
          />
          <span className={active ? "text-ok" : "text-warn"}>
            {active ? "Actif" : "Re-authentification requise"}
          </span>
        </span>
        <span className="text-ink-faint">·</span>
        <span className="text-ink-muted">{identity.statusNote}</span>
        <span className="text-ink-faint">·</span>
        <span className="text-ink-faint">
          synchro {relativeHours(identity.lastSyncHoursAgo)}
        </span>
      </div>
    </div>
  );
}
