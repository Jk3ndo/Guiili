"use client";

import type { ConnectionSummaryDto } from "@/lib/api/connections";

import { GoogleGlyph } from "./google-glyph";
import { IdentityCard } from "./identity-card";

export function IdentitiesSection({
  connections,
  isOwner,
  workspaceId,
  onChanged,
}: {
  connections: ConnectionSummaryDto[];
  isOwner: boolean;
  workspaceId: string | undefined;
  onChanged: () => void;
}) {
  return (
    <section className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-sm font-medium text-ink">Comptes Google liés</h2>
        {isOwner && workspaceId && (
          <a
            href={`/connections/google?workspace_id=${workspaceId}`}
            className="inline-flex h-9 items-center gap-2 rounded-lg border border-white/[0.08] bg-white/[0.03] px-3.5 text-xs font-medium text-ink-muted shadow-sm transition-colors hover:bg-white/[0.06] hover:text-ink"
          >
            <GoogleGlyph className="size-3.5" />
            Connecter un autre compte Google
          </a>
        )}
      </div>

      <div className="space-y-3">
        {connections.map((connection) => (
          <IdentityCard
            key={connection.id}
            connection={connection}
            isOwner={isOwner}
            workspaceId={workspaceId}
            onChanged={onChanged}
          />
        ))}
        {connections.length === 0 && (
          <p className="text-xs text-ink-muted">Aucun compte Google connecté.</p>
        )}
      </div>
    </section>
  );
}
