"use client";

import { toast } from "sonner";

import type { GoogleIdentity } from "@/lib/mock/connections";

import { GoogleGlyph } from "./google-glyph";
import { IdentityCard } from "./identity-card";

export function IdentitiesSection({
  identities,
}: {
  identities: GoogleIdentity[];
}) {
  return (
    <section className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-sm font-medium text-ink">Comptes Google liés</h2>
        <button
          type="button"
          onClick={() =>
            toast("Connexion d'un compte Google", {
              description: "Redirection vers le consentement Google (simulation).",
            })
          }
          className="inline-flex h-9 items-center gap-2 rounded-lg border border-white/[0.08] bg-white/[0.03] px-3.5 text-xs font-medium text-ink-muted shadow-sm transition-colors hover:bg-white/[0.06] hover:text-ink"
        >
          <GoogleGlyph className="size-3.5" />
          Connecter un autre compte Google
        </button>
      </div>

      <div className="space-y-3">
        {identities.map((identity) => (
          <IdentityCard key={identity.id} identity={identity} />
        ))}
      </div>
    </section>
  );
}
