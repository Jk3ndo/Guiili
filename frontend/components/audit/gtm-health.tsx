"use client";

import { useState } from "react";
import { ChevronDown, Loader2, ShieldCheck } from "lucide-react";

import { verifyGtmHeadless } from "@/lib/api/actions";
import type { GtmHealth as Gtm, GtmSeverity } from "@/lib/mock/audit";
import { cn } from "@/lib/utils";

const DOT: Record<GtmSeverity, string> = {
  high: "bg-danger",
  medium: "bg-warn",
  low: "bg-ink-faint",
};

const SNIPPET_LABEL: Record<string, string> = {
  standard: "Snippet standard",
  custom_loader: "Chargé par un loader tiers",
  noscript_only: "Balise <noscript> seule",
  absent: "Aucun conteneur détecté",
};

export function GtmHealth({ gtm, domain }: { gtm: Gtm | null; domain: string }) {
  const [open, setOpen] = useState<string | null>(null);
  const [verifying, setVerifying] = useState(false);

  async function onVerify() {
    setVerifying(true);
    try {
      await verifyGtmHeadless(domain);
    } finally {
      setVerifying(false);
    }
  }

  if (!gtm || !gtm.checked) {
    return (
      <section className="rounded-xl border border-white/[0.08] bg-surface/60 p-5 backdrop-blur-sm">
        <h2 className="text-sm font-medium text-ink">Santé du tag manager</h2>
        <p className="mt-1.5 text-xs text-ink-muted">
          Pas encore analysé — relance un diagnostic pour inspecter la
          configuration Google Tag Manager.
        </p>
      </section>
    );
  }

  return (
    <section className="overflow-hidden rounded-xl border border-white/[0.08] bg-surface/60 backdrop-blur-sm">
      <header className="flex items-center justify-between gap-3 border-b border-white/[0.05] px-5 py-3">
        <div>
          <h2 className="text-sm font-medium text-ink">Santé du tag manager</h2>
          {gtm.headlessCheckedAt ? (
            <p className="mt-0.5 text-[11px] text-ink-faint">
              Vérifié en conditions réelles le{" "}
              {new Date(gtm.headlessCheckedAt).toLocaleString("fr-FR")}
            </p>
          ) : null}
        </div>
        <button
          type="button"
          onClick={() => void onVerify()}
          disabled={verifying}
          className="inline-flex h-8 shrink-0 items-center gap-1.5 rounded-lg border border-white/[0.08] bg-white/[0.03] px-3 text-xs font-medium text-ink-muted transition-colors hover:bg-white/[0.06] hover:text-ink disabled:opacity-60"
        >
          {verifying ? (
            <Loader2 className="size-3.5 animate-spin" />
          ) : (
            <ShieldCheck className="size-3.5" />
          )}
          {verifying ? "Vérification…" : "Vérifier en conditions réelles"}
        </button>
      </header>

      <dl className="grid grid-cols-2 gap-x-6 gap-y-3 px-5 py-4 text-xs sm:grid-cols-4">
        <div>
          <dt className="text-ink-faint">Conteneurs</dt>
          <dd className="mt-0.5 font-mono text-ink">
            {gtm.containers.length ? gtm.containers.join(", ") : "—"}
          </dd>
        </div>
        <div>
          <dt className="text-ink-faint">Installation</dt>
          <dd className="mt-0.5 text-ink">
            {SNIPPET_LABEL[gtm.snippetForm] ?? gtm.snippetForm}
          </dd>
        </div>
        <div>
          <dt className="text-ink-faint">Consentement</dt>
          <dd className="mt-0.5 text-ink">
            {gtm.consentPlatform ?? "Aucune CMP détectée"}
          </dd>
        </div>
        <div>
          <dt className="text-ink-faint">Objet data layer</dt>
          <dd className="mt-0.5 font-mono text-ink">{gtm.dataLayerName}</dd>
        </div>
      </dl>

      {gtm.findings.length > 0 ? (
        <ul className="border-t border-white/[0.05]">
          {gtm.findings.map((finding) => (
            <li
              key={finding.code}
              className="border-b border-white/[0.05] last:border-0"
            >
              <button
                type="button"
                onClick={() =>
                  setOpen(open === finding.code ? null : finding.code)
                }
                className="flex w-full items-center gap-2.5 px-5 py-3 text-left transition-colors hover:bg-white/[0.02]"
              >
                <span
                  className={cn(
                    "size-1.5 shrink-0 rounded-full",
                    DOT[finding.severity],
                  )}
                />
                <span className="flex-1 text-xs text-ink">{finding.title}</span>
                <ChevronDown
                  className={cn(
                    "size-4 shrink-0 text-ink-faint transition-transform",
                    open === finding.code && "rotate-180",
                  )}
                />
              </button>
              {open === finding.code ? (
                <p className="px-5 pb-3 pl-[2.375rem] text-xs leading-relaxed text-ink-muted">
                  {finding.detail}
                </p>
              ) : null}
            </li>
          ))}
        </ul>
      ) : (
        <p className="border-t border-white/[0.05] px-5 py-3 text-xs text-ink-muted">
          Aucun problème détecté sur la configuration GTM.
        </p>
      )}
    </section>
  );
}
