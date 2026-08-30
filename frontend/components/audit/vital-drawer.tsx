"use client";

import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import {
  VITAL_SOURCE_LABEL,
  type ClsDiagnostic,
  type InpDiagnostic,
  type LcpDiagnostic,
  type VitalSource,
  type WebVital,
} from "@/lib/mock/audit";
import { cn } from "@/lib/utils";

import { CopyButton } from "../backlog/copy-button";

const SOURCE_TONE: Record<VitalSource, string> = {
  field: "text-ok",
  lab: "text-ink-muted",
};

function SourceBadge({ source }: { source: VitalSource }) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-md border border-white/[0.08] bg-white/[0.02] px-2 py-1 text-2xs font-medium",
        SOURCE_TONE[source],
      )}
    >
      <span
        className={cn(
          "size-1.5 rounded-full",
          source === "field" ? "bg-ok" : "bg-ink-faint",
        )}
      />
      {VITAL_SOURCE_LABEL[source]}
    </span>
  );
}

function Field({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div className="space-y-1.5">
      <p className="text-2xs font-medium text-ink-faint">{label}</p>
      {children}
    </div>
  );
}

function SnippetBlock({ code, label }: { code: string; label: string }) {
  return (
    <div className="overflow-hidden rounded-xl border border-white/[0.08] bg-surface/40">
      <div className="flex items-center justify-between border-b border-white/[0.06] bg-white/[0.02] px-3 py-1.5">
        <span className="font-mono text-2xs text-ink-faint">{label}</span>
        <CopyButton text={code} label="Copier" />
      </div>
      <pre className="overflow-x-auto px-3 py-2.5 font-mono text-2xs leading-relaxed text-ink">
        {code}
      </pre>
    </div>
  );
}

function Recommendations({ items }: { items: string[] }) {
  if (items.length === 0) return null;
  return (
    <Field label="Recommandation technique">
      <ul className="space-y-2 rounded-xl border border-white/[0.08] bg-surface/40 p-4">
        {items.map((item) => (
          <li
            key={item}
            className="flex gap-2.5 text-xs leading-relaxed text-ink-muted"
          >
            <span className="mt-1.5 size-1 shrink-0 rounded-full bg-ink-faint" />
            <span>{item}</span>
          </li>
        ))}
      </ul>
    </Field>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-white/[0.08] bg-surface/40 px-3 py-2.5">
      <p className="text-2xs text-ink-faint">{label}</p>
      <p className="mt-0.5 font-mono text-sm text-ink tabular-nums">{value}</p>
    </div>
  );
}

function InpBody({ diagnostic }: { diagnostic: InpDiagnostic }) {
  return (
    <>
      <SourceBadge source={diagnostic.source} />

      <div className="grid grid-cols-2 gap-2.5">
        <Metric
          label="Temps de blocage total"
          value={`${diagnostic.totalBlockingTimeMs} ms`}
        />
        <Metric
          label="Exécution JS totale"
          value={`${diagnostic.jsExecutionMs} ms`}
        />
      </div>

      <Field label="Scripts tiers et entités coûteuses">
        {diagnostic.entities.length === 0 ? (
          <p className="text-xs text-ink-muted">
            Aucune entité tierce coûteuse identifiée dans le rapport.
          </p>
        ) : (
          <ul className="overflow-hidden rounded-xl border border-white/[0.08] bg-surface/40">
            {diagnostic.entities.map((entity) => (
              <li
                key={entity.name}
                className="flex items-center justify-between gap-3 border-t border-white/[0.05] px-3 py-2.5 first:border-t-0"
              >
                <span className="min-w-0">
                  <span className="block truncate text-xs text-ink">
                    {entity.name}
                  </span>
                  <span className="block text-2xs text-ink-faint">
                    {entity.category}
                  </span>
                </span>
                <span className="shrink-0 text-right">
                  <span className="block font-mono text-xs text-ink tabular-nums">
                    {entity.mainThreadMs} ms
                  </span>
                  <span className="block font-mono text-2xs text-ink-faint tabular-nums">
                    dont {entity.blockingMs} ms bloquants
                  </span>
                </span>
              </li>
            ))}
          </ul>
        )}
      </Field>

      <Recommendations items={diagnostic.recommendations} />
    </>
  );
}

function LcpBody({ diagnostic }: { diagnostic: LcpDiagnostic }) {
  return (
    <>
      <SourceBadge source={diagnostic.source} />

      {diagnostic.elementSnippet && (
        <Field label="Élément LCP">
          <SnippetBlock code={diagnostic.elementSnippet} label="nœud DOM" />
        </Field>
      )}

      {diagnostic.assets.length > 0 && (
        <Field label="Assets à optimiser">
          <ul className="overflow-hidden rounded-xl border border-white/[0.08] bg-surface/40">
            {diagnostic.assets.map((asset) => (
              <li
                key={asset.name}
                className="flex items-center justify-between gap-3 border-t border-white/[0.05] px-3 py-2.5 first:border-t-0"
              >
                <span className="min-w-0">
                  <span className="block truncate font-mono text-xs text-ink">
                    {asset.name}
                  </span>
                  <span className="block text-2xs text-ink-faint">
                    {asset.currentFormat} · {asset.sizeKb} ko
                  </span>
                </span>
                <span className="shrink-0 text-right">
                  {asset.estimatedSavingKb > 0 ? (
                    <>
                      <span className="block font-mono text-xs text-ok tabular-nums">
                        −{asset.estimatedSavingKb} ko
                      </span>
                      <span className="block text-2xs text-ink-faint">
                        via AVIF / WebP
                      </span>
                    </>
                  ) : (
                    <span className="block text-2xs text-ink-faint">
                      à découper / différer
                    </span>
                  )}
                </span>
              </li>
            ))}
          </ul>
        </Field>
      )}

      {diagnostic.preloadHint && (
        <Field label="Préchargement recommandé">
          <SnippetBlock code={diagnostic.preloadHint} label="dans le <head>" />
        </Field>
      )}

      <Recommendations items={diagnostic.recommendations} />
    </>
  );
}

function ClsBody({ diagnostic }: { diagnostic: ClsDiagnostic }) {
  return (
    <>
      <SourceBadge source={diagnostic.source} />

      <Field label="Éléments à l'origine des décalages">
        {diagnostic.elements.length === 0 ? (
          <p className="text-xs text-ink-muted">
            Aucun décalage significatif isolé dans le rapport.
          </p>
        ) : (
          <ul className="overflow-hidden rounded-xl border border-white/[0.08] bg-surface/40">
            {diagnostic.elements.map((element) => (
              <li
                key={element.selector}
                className="space-y-1 border-t border-white/[0.05] px-3 py-2.5 first:border-t-0"
              >
                <div className="flex items-center justify-between gap-3">
                  <span className="min-w-0 truncate font-mono text-2xs text-ink">
                    {element.selector}
                  </span>
                  <span className="shrink-0 font-mono text-2xs text-warn tabular-nums">
                    +{element.impact.toFixed(2)}
                  </span>
                </div>
                <p className="text-2xs leading-relaxed text-ink-muted">
                  {element.note}
                </p>
              </li>
            ))}
          </ul>
        )}
      </Field>

      <Recommendations items={diagnostic.recommendations} />
    </>
  );
}

export function VitalDrawer({
  vital,
  onOpenChange,
}: {
  vital: WebVital | null;
  onOpenChange: (open: boolean) => void;
}) {
  const diagnostic = vital?.diagnostic ?? null;

  return (
    <Sheet open={diagnostic !== null} onOpenChange={onOpenChange}>
      <SheetContent
        side="right"
        className="w-full gap-0 border-l-white/[0.1] bg-surface p-0 sm:max-w-lg"
      >
        {vital && diagnostic && (
          <>
            <SheetHeader className="gap-2 border-b border-white/[0.06] p-5 pr-12">
              <div className="flex items-center gap-2 text-2xs">
                <span className="font-mono font-medium text-ink-muted">
                  {vital.id.toUpperCase()}
                </span>
                <span className="text-ink-faint">·</span>
                <span className="font-mono text-ink tabular-nums">
                  {vital.value}
                </span>
                <span className="text-ink-faint">·</span>
                <span className="text-ink-faint">cible {vital.target}</span>
              </div>
              <SheetTitle className="text-sm leading-snug font-semibold text-ink">
                {vital.label}
              </SheetTitle>
              <SheetDescription className="text-xs leading-relaxed text-ink-muted">
                Diagnostic des causes identifiées par la sonde PageSpeed.
              </SheetDescription>
            </SheetHeader>

            <div className="flex-1 space-y-5 overflow-y-auto p-5">
              {diagnostic.kind === "inp" && <InpBody diagnostic={diagnostic} />}
              {diagnostic.kind === "lcp" && <LcpBody diagnostic={diagnostic} />}
              {diagnostic.kind === "cls" && <ClsBody diagnostic={diagnostic} />}
            </div>
          </>
        )}
      </SheetContent>
    </Sheet>
  );
}
