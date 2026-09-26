"use client";

import { Loader2 } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";

import { PageShell } from "@/components/shell/page-shell";
import {
  autolinkGoogle,
  describeMeasurementError,
  fetchMeasurementPlan,
  isStale,
  refreshMeasurementPlan,
  type AutolinkSummary,
  type MeasurementItemDto,
  type MeasurementLayer,
  type MeasurementPlanDto,
} from "@/lib/api/measurement";
import { useIsOwner } from "@/lib/api/use-is-owner";
import { useShell } from "@/lib/shell/shell-context";

import { AdsSettings } from "./ads-settings";
import { AutoTrackingCard } from "./auto-tracking-card";
import { AdvancedContainer, StarterPackCard } from "./container-builder";
import { formatDateTime, truncate } from "./format";
import { GoogleStep } from "./google-step";
import { ItemDrawer } from "./item-drawer";
import { LAYER_LABEL } from "./labels";
import { NextActions } from "./next-actions";
import { PlanItemRow } from "./plan-item-row";
import { PlanProgress } from "./plan-progress";
import { ProfileBanner } from "./profile-banner";

const LAYERS: MeasurementLayer[] = ["foundations", "events", "conversions", "ads", "seo"];

const SUBTITLE =
  "Ce qu'il faut mettre en place pour mesurer ton trafic et tes conversions, dans l'ordre. Chaque « fait » est prouvé ou déclaré par toi.";

function needsGoogleLinks(plan: MeasurementPlanDto): boolean {
  return plan.google_connection === "active" && (!plan.ga4_connected || !plan.gsc_linked);
}

function PlanPanel({
  websiteId,
  domain,
  realWorkspaceId,
}: {
  websiteId: string;
  domain: string;
  realWorkspaceId: string | undefined;
}) {
  const isOwner = useIsOwner(realWorkspaceId);

  const [plan, setPlan] = useState<MeasurementPlanDto | null>(null);
  const [status, setStatus] = useState<"loading" | "loaded" | "error">("loading");
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [realConditions, setRealConditions] = useState(false);
  const [openId, setOpenId] = useState<string | null>(null);
  const [selectMode, setSelectMode] = useState(false);
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [autolink, setAutolink] = useState<AutolinkSummary | null>(null);
  const [linkError, setLinkError] = useState<string | null>(null);
  const [linkPending, setLinkPending] = useState(true);
  // Une seule tentative d'auto-liaison par ouverture de la page.
  const autolinkTried = useRef(false);
  // Numéro de la passe en cours : une réponse qui arrive après un rechargement ou après le
  // démontage de la page (changement de site) est ignorée.
  const runId = useRef(0);

  const refresh = useCallback(
    async (
      id: string,
      headless: boolean,
      isCurrent: () => boolean,
    ): Promise<MeasurementPlanDto | null> => {
      setRefreshing(true);
      try {
        const next = await refreshMeasurementPlan(id, headless);
        if (!isCurrent()) return null;
        setPlan(next);
        if (next.headless_skipped) {
          const when = formatDateTime(next.headless_checked_at);
          toast("Vérification en conditions réelles déjà faite il y a moins de 5 minutes", {
            description: when
              ? `Dernier passage : ${when}. Les autres vérifications ont été relancées.`
              : "Les autres vérifications ont été relancées.",
          });
        }
        if (next.headless_error) {
          // Texte français fixe du backend (jamais le détail du navigateur) : rendu en texte brut.
          toast.error("Le navigateur de vérification a échoué", {
            description: truncate(next.headless_error),
          });
        }
        return next;
      } catch (err) {
        if (isCurrent()) toast.error(describeMeasurementError(err));
        return null;
      } finally {
        setRefreshing(false);
      }
    },
    [],
  );

  const runAutolink = useCallback(async (id: string, isCurrent: () => boolean) => {
    try {
      const result = await autolinkGoogle(id);
      if (!isCurrent()) return;
      setAutolink({ ga4: result.ga4, gsc: result.gsc });
      // Le plan renvoyé est déjà rafraîchi par le backend : pas de second refresh.
      setPlan(result.plan);
      if (result.ga4.status === "linked" || result.gsc.status === "linked") {
        toast("Google relié à ce site", {
          description: "Ton plan a été revérifié avec tes vraies données.",
        });
      }
    } catch (err) {
      // L'étape Google garde un lien vers « Connexions Google ».
      if (isCurrent()) setLinkError(describeMeasurementError(err));
    }
  }, []);

  const load = useCallback(
    async (id: string) => {
      const run = ++runId.current;
      const isCurrent = () => runId.current === run;
      let latest: MeasurementPlanDto;
      try {
        latest = await fetchMeasurementPlan(id);
      } catch (err) {
        if (isCurrent()) {
          setError(describeMeasurementError(err));
          setStatus("error");
        }
        return;
      }
      if (!isCurrent()) return;
      setPlan(latest);
      setStatus("loaded");

      if (isStale(latest.last_checked_at)) {
        const refreshed = await refresh(id, false, isCurrent);
        if (!isCurrent()) return;
        if (refreshed) latest = refreshed;
      }
      if (needsGoogleLinks(latest) && !autolinkTried.current) {
        autolinkTried.current = true;
        await runAutolink(id, isCurrent);
      }
      if (isCurrent()) setLinkPending(false);
    },
    [refresh, runAutolink],
  );

  useEffect(() => {
    void load(websiteId);
    return () => {
      runId.current += 1;
    };
  }, [websiteId, load]);

  const byLayer = useMemo(() => {
    const groups = new Map<MeasurementLayer, MeasurementItemDto[]>();
    for (const layer of LAYERS) groups.set(layer, []);
    for (const item of plan?.items ?? []) {
      if (item.state === "not_applicable") continue;
      groups.get(item.layer)?.push(item);
    }
    return groups;
  }, [plan]);

  if (status === "loading" && !plan) return null;

  if (status === "error" || !plan) {
    return (
      <PageShell title="Plan de mesure" subtitle={SUBTITLE}>
        <div className="space-y-3">
          <p className="text-xs text-ink-muted">
            Impossible de charger le plan de mesure{error ? ` : ${error}` : "."}
          </p>
          <button
            type="button"
            onClick={() => {
              setStatus("loading");
              setError(null);
              void load(websiteId);
            }}
            className="inline-flex h-9 items-center rounded-lg border border-white/[0.08] bg-white/[0.03] px-3.5 text-xs font-medium text-ink-muted transition-colors hover:bg-white/[0.06] hover:text-ink"
          >
            Réessayer
          </button>
        </div>
      </PageShell>
    );
  }

  const openItem = plan.items.find((item) => item.id === openId) ?? null;
  const selectable = plan.items.filter(
    (item) => item.actions.includes("gtm_container") && item.state !== "not_applicable",
  );
  const selectableIds = selectable.map((item) => item.id);
  // Une ligne devenue « non concernée » depuis la sélection ne part pas dans le conteneur.
  const effectiveSelectedIds = selectedIds.filter((id) => selectableIds.includes(id));
  const missingIds = selectable
    .filter((item) => item.state !== "dismissed" && !item.done)
    .map((item) => item.id);
  const visibleCount = Array.from(byLayer.values()).reduce((sum, list) => sum + list.length, 0);
  const headlessAt = formatDateTime(plan.headless_checked_at);
  const firstCheckPending = refreshing && plan.last_checked_at === null;

  return (
    <PageShell
      title="Plan de mesure"
      subtitle={SUBTITLE}
      actions={
        <div className="flex flex-wrap items-center gap-3">
          <label className="flex items-center gap-2 text-xs text-ink-muted">
            <input
              type="checkbox"
              checked={realConditions}
              onChange={(event) => setRealConditions(event.target.checked)}
              className="size-3.5 accent-zinc-200"
            />
            En conditions réelles
          </label>
          <button
            type="button"
            disabled={refreshing}
            onClick={() => {
              const run = runId.current;
              void refresh(websiteId, realConditions, () => runId.current === run);
            }}
            className="inline-flex h-9 items-center gap-2 rounded-lg bg-zinc-100 px-4 text-xs font-medium text-zinc-950 shadow-sm transition-colors hover:bg-zinc-200 disabled:opacity-60"
          >
            {refreshing && <Loader2 className="size-3.5 animate-spin" />}
            Vérifier maintenant
          </button>
        </div>
      }
    >
      <ProfileBanner
        key={plan.profile.effective_types.join(",")}
        websiteId={websiteId}
        plan={plan}
        isOwner={isOwner}
        onChanged={setPlan}
      />

      {firstCheckPending && (
        <p className="flex items-center gap-2 text-xs text-ink-muted" role="status">
          <Loader2 className="size-3.5 animate-spin" />
          Première vérification de ton site en cours…
        </p>
      )}

      <PlanProgress plan={plan} />
      {headlessAt && (
        <p className="-mt-3 text-2xs text-ink-faint">
          Dernière vérification en conditions réelles : {headlessAt}.
        </p>
      )}

      <GoogleStep plan={plan} autolink={autolink} linkError={linkError} pending={linkPending} />

      <NextActions plan={plan} onOpen={setOpenId} />

      <StarterPackCard websiteId={websiteId} plan={plan} />

      <AutoTrackingCard websiteId={websiteId} />

      <details className="group rounded-xl border border-white/[0.08] bg-surface/30">
        <summary className="cursor-pointer select-none px-5 py-4 text-sm font-medium text-ink">
          Pour aller plus loin{" "}
          <span className="font-normal text-ink-muted">
            ({visibleCount} ligne{visibleCount > 1 ? "s" : ""}, conteneur personnalisé, publicité)
          </span>
        </summary>
        <div className="space-y-6 px-5 pb-5">
          {LAYERS.map((layer) => {
            const items = byLayer.get(layer) ?? [];
            if (items.length === 0) return null;
            return (
              <section key={layer} className="space-y-2">
                <h2 className="text-sm font-medium text-ink">{LAYER_LABEL[layer]}</h2>
                <div className="overflow-hidden rounded-xl border border-white/[0.08] bg-surface/30">
                  {items.map((item) => (
                    <PlanItemRow
                      key={item.id}
                      item={item}
                      onOpen={() => setOpenId(item.id)}
                      selectable={selectMode && selectableIds.includes(item.id)}
                      selected={selectedIds.includes(item.id)}
                      onToggle={() =>
                        setSelectedIds((current) =>
                          current.includes(item.id)
                            ? current.filter((id) => id !== item.id)
                            : [...current, item.id],
                        )
                      }
                    />
                  ))}
                </div>
              </section>
            );
          })}

          <AdvancedContainer
            websiteId={websiteId}
            plan={plan}
            selectMode={selectMode}
            onToggleSelectMode={() => setSelectMode((value) => !value)}
            selectedIds={effectiveSelectedIds}
            onSelectMissing={() => setSelectedIds(missingIds)}
            onClear={() => setSelectedIds([])}
          />

          <AdsSettings
            key={JSON.stringify(plan.profile.params)}
            websiteId={websiteId}
            plan={plan}
            isOwner={isOwner}
            onChanged={setPlan}
          />
        </div>
      </details>

      <ItemDrawer
        item={openItem}
        websiteId={websiteId}
        isOwner={isOwner}
        domain={domain}
        onClose={() => setOpenId(null)}
        onChanged={setPlan}
      />
    </PageShell>
  );
}

export function PlanView() {
  const { workspace } = useShell();

  if (!workspace.websiteId) {
    return (
      <PageShell title="Plan de mesure" subtitle={SUBTITLE}>
        <p className="text-xs text-ink-muted">
          Ajoute un site réel pour obtenir son plan de mesure (les sites de démonstration n&apos;en
          ont pas).
        </p>
      </PageShell>
    );
  }

  // `key` : changer de site repart d'un état neuf (plan, sélection, tiroir, auto-liaison).
  return (
    <PlanPanel
      key={workspace.websiteId}
      websiteId={workspace.websiteId}
      domain={workspace.domain}
      realWorkspaceId={workspace.realWorkspaceId}
    />
  );
}
