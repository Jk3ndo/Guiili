"use client";

import { ChevronDown, LineChart, Search, type LucideIcon } from "lucide-react";

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import type { WebsiteGoogleLinkDto } from "@/lib/api/connections";

const ICON: Record<"ga4_property" | "gsc_site", LucideIcon> = {
  ga4_property: LineChart,
  gsc_site: Search,
};

interface Option {
  id: string;
  label: string;
  connectionId: string;
  sourceEmail: string;
}

export function ResourceRow({
  typeLabel,
  typeNoun,
  resourceType,
  options,
  linked,
  isOwner,
  onChange,
}: {
  typeLabel: string;
  typeNoun: string;
  resourceType: "ga4_property" | "gsc_site";
  options: Option[];
  linked: WebsiteGoogleLinkDto | null;
  isOwner: boolean;
  onChange: (type: "ga4_property" | "gsc_site", resourceId: string, connectionId: string, displayName: string) => void;
}) {
  const Icon = ICON[resourceType];
  const linkedOption = options.find((o) => o.id === linked?.resource_id) ?? null;

  return (
    <div className="rounded-xl border border-white/[0.08] bg-surface/60 p-5 backdrop-blur-sm">
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-start gap-3">
          <span className="mt-0.5 flex size-8 shrink-0 items-center justify-center rounded-lg border border-white/[0.08] bg-white/[0.03] text-ink-muted">
            <Icon className="size-4" />
          </span>
          <div className="space-y-0.5">
            <p className="text-sm font-medium text-ink">{typeLabel}</p>
            <p className="text-xs text-ink-faint">{typeNoun}</p>
          </div>
        </div>

        {isOwner && options.length > 0 && (
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <button
                type="button"
                className="inline-flex h-8 shrink-0 items-center gap-1.5 rounded-lg border border-white/[0.08] bg-white/[0.03] px-2.5 text-xs font-medium text-ink-muted shadow-sm transition-colors hover:bg-white/[0.06] hover:text-ink"
              >
                Changer
                <ChevronDown className="size-3.5" />
              </button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-72">
              <DropdownMenuLabel className="text-2xs font-medium text-ink-faint">
                Ressources {typeLabel} découvertes
              </DropdownMenuLabel>
              <DropdownMenuRadioGroup
                value={linked?.resource_id ?? ""}
                onValueChange={(value) => {
                  const option = options.find((o) => o.id === value);
                  if (option) onChange(resourceType, option.id, option.connectionId, option.label);
                }}
              >
                {options.map((option) => (
                  <DropdownMenuRadioItem
                    key={option.id}
                    value={option.id}
                    className="flex-col items-start gap-0.5 py-2"
                  >
                    <span className="text-xs font-medium text-ink">{option.label}</span>
                    <span className="font-mono text-2xs text-ink-faint">{option.id}</span>
                    <span className="text-2xs text-ink-faint">via {option.sourceEmail}</span>
                  </DropdownMenuRadioItem>
                ))}
              </DropdownMenuRadioGroup>
            </DropdownMenuContent>
          </DropdownMenu>
        )}
      </div>

      <div className="mt-4 border-t border-white/[0.06] pt-3">
        {linked ? (
          <div className="space-y-1">
            <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
              <span className="text-sm font-medium text-ink">
                {linkedOption?.label ?? linked.resource_display_name ?? linked.resource_id}
              </span>
              <span className="font-mono text-2xs text-ink-muted">{linked.resource_id}</span>
            </div>
          </div>
        ) : (
          <p className="text-xs text-ink-muted">Aucune ressource assignée.</p>
        )}
      </div>
    </div>
  );
}
