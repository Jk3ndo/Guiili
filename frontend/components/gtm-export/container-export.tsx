"use client";

import { Braces, Download, Package, Tag, Zap, type LucideIcon } from "lucide-react";
import { toast } from "sonner";

import { downloadGtmContainer } from "@/lib/api/actions";
import { saveBlob } from "@/lib/api/client";
import {
  buildGtmContainer,
  containerRef,
  EXPORT_ELEMENTS,
  type GtmElementKind,
} from "@/lib/mock/gtm-export";
import type { Workspace } from "@/lib/mock/types";

import { ImportGuide } from "./import-guide";

const KIND_ICON: Record<GtmElementKind, LucideIcon> = {
  tag: Tag,
  trigger: Zap,
  variable: Braces,
};

const KIND_LABEL: Record<GtmElementKind, string> = {
  tag: "Balise",
  trigger: "Déclencheur",
  variable: "Variable",
};

export function ContainerExport({ workspace }: { workspace: Workspace }) {
  const { publicId } = containerRef(workspace);

  async function handleDownload() {
    if (await downloadGtmContainer(workspace.domain)) return;

    // Fallback mode démo : conteneur généré côté client.
    const json = JSON.stringify(buildGtmContainer(workspace), null, 2);
    saveBlob(
      new Blob([json], { type: "application/json" }),
      `gtm-container-${publicId}.json`,
    );
    toast.success("Conteneur GTM téléchargé (mode démo)", {
      description: `${publicId} · format v2 · ${EXPORT_ELEMENTS.length} éléments`,
    });
  }

  return (
    <section className="space-y-4">
      <div className="rounded-xl border border-white/[0.08] bg-surface/60 p-5 backdrop-blur-sm">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="flex items-center gap-2.5">
            <span className="flex size-8 shrink-0 items-center justify-center rounded-lg border border-white/[0.08] bg-white/[0.03]">
              <Package className="size-4 text-ink-muted" />
            </span>
            <div>
              <p className="text-sm font-medium text-ink">
                Conteneur {publicId}
              </p>
              <p className="text-xs text-ink-faint">{workspace.domain}</p>
            </div>
          </div>
          <span className="inline-flex items-center rounded-md border border-white/[0.08] bg-white/[0.02] px-2 py-1 font-mono text-2xs text-ink-muted">
            exportFormatVersion: 2
          </span>
        </div>

        <ul className="mt-4 divide-y divide-white/[0.05] border-t border-white/[0.06]">
          {EXPORT_ELEMENTS.map((element) => {
            const Icon = KIND_ICON[element.kind];
            return (
              <li key={element.name} className="flex items-start gap-3 py-2.5">
                <Icon className="mt-0.5 size-3.5 shrink-0 text-ink-faint" />
                <div className="min-w-0">
                  <p className="text-xs font-medium text-ink">
                    <span className="text-ink-faint">
                      {KIND_LABEL[element.kind]}
                      {" · "}
                    </span>
                    {element.name}
                  </p>
                  <p className="text-xs text-ink-muted">{element.detail}</p>
                </div>
              </li>
            );
          })}
        </ul>

        <button
          type="button"
          onClick={() => void handleDownload()}
          className="mt-5 inline-flex h-9 items-center gap-2 rounded-lg bg-zinc-100 px-4 text-xs font-medium text-zinc-950 shadow-sm transition-colors hover:bg-zinc-200"
        >
          <Download className="size-3.5" />
          Télécharger le conteneur JSON (GTM)
        </button>
      </div>

      <ImportGuide />
    </section>
  );
}
