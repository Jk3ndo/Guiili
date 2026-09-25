"use client";

import { Loader2 } from "lucide-react";
import Link from "next/link";

import type {
  AutolinkSummary,
  LinkOutcomeDto,
  MeasurementPlanDto,
} from "@/lib/api/measurement";

const BUTTON =
  "inline-flex h-9 items-center rounded-lg bg-zinc-100 px-4 text-xs font-medium text-zinc-950 shadow-sm transition-colors hover:bg-zinc-200";
const CARD = "space-y-2 rounded-xl border border-white/[0.08] bg-surface/60 p-5";

/** Le texte vient du backend (`message`) : on l'affiche tel quel, seulement pour un côté
 * qui n'est pas encore lié. Une liaison déjà faite n'a rien à expliquer. */
function explain(label: string, linked: boolean, outcome: LinkOutcomeDto): string | null {
  if (linked) return null;
  if (outcome.status === "linked" || outcome.status === "already_linked") return null;
  if (!outcome.message) return null;
  return `${label} : ${outcome.message}`;
}

/** Palier 2 : un clic pour relier Google. Rien n'est affiché quand tout est déjà lié. */
export function GoogleStep({
  plan,
  autolink,
  linkError,
  pending,
}: {
  plan: MeasurementPlanDto;
  autolink: AutolinkSummary | null;
  linkError: string | null;
  /** Vrai tant que la liaison automatique n'a pas eu lieu (ou est en cours). */
  pending: boolean;
}) {
  if (plan.google_connection === "none") {
    return (
      <section className="flex flex-wrap items-center justify-between gap-4 rounded-xl border border-white/[0.08] bg-surface/60 p-5">
        <div className="max-w-xl space-y-1">
          <p className="text-sm font-medium text-ink">Connecte Google pour voir tes vraies données</p>
          <p className="text-xs leading-relaxed text-ink-muted">
            Un clic : on relie automatiquement Google Analytics et Search Console à ce site, et les
            lignes du plan passent à « Reçu par GA4 » quand les données arrivent.
          </p>
        </div>
        <Link href="/connections" className={BUTTON}>
          Connecter Google
        </Link>
      </section>
    );
  }

  if (plan.google_connection === "needs_reauth") {
    return (
      <section className="flex flex-wrap items-center justify-between gap-4 rounded-xl border border-white/[0.08] bg-surface/60 p-5">
        <div className="max-w-xl space-y-1">
          <p className="text-sm font-medium text-ink">Ta connexion Google est à renouveler</p>
          <p className="text-xs leading-relaxed text-ink-muted">
            Reconnecte ton compte pour que les données GA4 et Search Console reviennent.
          </p>
        </div>
        <Link href="/connections" className={BUTTON}>
          Reconnecter Google
        </Link>
      </section>
    );
  }

  if (plan.ga4_connected && plan.gsc_linked) return null;

  if (pending) {
    return (
      <p className="flex items-center gap-2 text-xs text-ink-muted" role="status">
        <Loader2 className="size-3.5 animate-spin" />
        On relie ton compte Google à ce site…
      </p>
    );
  }

  const messages: string[] = linkError
    ? [linkError]
    : autolink
      ? [
          explain("Google Analytics", plan.ga4_connected, autolink.ga4),
          explain("Search Console", plan.gsc_linked, autolink.gsc),
        ].filter((message): message is string => message !== null)
      : [];
  if (messages.length === 0) {
    messages.push("Relie Google Analytics et Search Console à ce site dans « Connexions Google ».");
  }

  return (
    <section className={CARD}>
      <p className="text-sm font-medium text-ink">Une dernière liaison à faire</p>
      <ul className="space-y-1 text-xs leading-relaxed text-ink-muted">
        {messages.map((message, index) => (
          <li key={index}>{message}</li>
        ))}
      </ul>
      <Link href="/connections" className={BUTTON}>
        Ouvrir « Connexions Google »
      </Link>
    </section>
  );
}
