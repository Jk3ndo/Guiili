"use client";

import { Plug, RotateCw } from "lucide-react";
import { toast } from "sonner";

import { ApiError } from "@/lib/api/client";
import { disconnectConnection, type ConnectionSummaryDto } from "@/lib/api/connections";
import { relativeHours } from "@/lib/format";
import { cn } from "@/lib/utils";

import { GoogleGlyph } from "./google-glyph";

/** `relativeHours` (lib/format.ts, deja utilise par identity-card en mode
 * mock) attend un nombre d'heures — converti ici depuis le timestamp reel. */
function hoursAgo(iso: string | null): number | null {
  if (!iso) return null;
  return Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 3_600_000));
}

export function IdentityCard({
  connection,
  isOwner,
  workspaceId,
  onChanged,
}: {
  connection: ConnectionSummaryDto;
  isOwner: boolean;
  workspaceId: string | undefined;
  onChanged: () => void;
}) {
  const active = connection.status === "active";
  const needsReauth = connection.status === "needs_reauth";
  const hours = hoursAgo(connection.last_refreshed_at);

  async function handleDisconnect() {
    try {
      await disconnectConnection(connection.id);
      toast("Compte déconnecté", { description: connection.email });
      onChanged();
    } catch (error) {
      toast.error(error instanceof ApiError ? error.message : "Déconnexion impossible");
    }
  }

  return (
    <div className="rounded-xl border border-white/[0.08] bg-surface/60 p-5 backdrop-blur-sm">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex items-start gap-3">
          <span className="mt-0.5 flex size-8 shrink-0 items-center justify-center rounded-lg border border-white/[0.08] bg-white/[0.03] text-ink-muted">
            <GoogleGlyph className="size-4" />
          </span>
          <p className="text-sm font-medium text-ink">{connection.email}</p>
        </div>

        {isOwner &&
          (needsReauth && workspaceId ? (
            <a
              href={`/connections/google?workspace_id=${workspaceId}`}
              className="inline-flex h-8 shrink-0 items-center gap-1.5 rounded-lg border border-warn/40 bg-warn/10 px-2.5 text-xs font-medium text-warn shadow-sm transition-colors hover:bg-warn/15"
            >
              <RotateCw className="size-3.5" />
              Re-synchroniser
            </a>
          ) : active ? (
            <button
              type="button"
              onClick={() => void handleDisconnect()}
              className="inline-flex h-8 shrink-0 items-center gap-1.5 rounded-lg border border-white/[0.08] bg-white/[0.03] px-2.5 text-xs font-medium text-ink-muted shadow-sm transition-colors hover:bg-white/[0.06] hover:text-ink"
            >
              <Plug className="size-3.5" />
              Déconnecter
            </button>
          ) : null)}
      </div>

      <div className="mt-4 flex flex-wrap items-center gap-1.5">
        {connection.granted_scopes.map((scope) => (
          <span
            key={scope}
            className="inline-flex h-[18px] items-center rounded border border-hairline bg-white/[0.03] px-1.5 font-mono text-2xs text-ink-muted"
          >
            {scope.replace("https://www.googleapis.com/auth/", "")}
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
            {active ? "Actif" : needsReauth ? "Re-authentification requise" : "Déconnecté"}
          </span>
        </span>
        {hours !== null && (
          <>
            <span className="text-ink-faint">·</span>
            <span className="text-ink-faint">synchro {relativeHours(hours)}</span>
          </>
        )}
      </div>
    </div>
  );
}
