"use client";

import { ChevronDown, Container, LineChart, Search, type LucideIcon } from "lucide-react";

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  linkedOption,
  RESOURCE_META,
  type ResourceLink,
  type ResourceType,
} from "@/lib/mock/connections";

const ICON: Record<ResourceType, LucideIcon> = {
  ga4: LineChart,
  gtm: Container,
  gsc: Search,
};

export function ResourceRow({
  link,
  onChange,
}: {
  link: ResourceLink;
  onChange: (type: ResourceType, id: string) => void;
}) {
  const meta = RESOURCE_META[link.type];
  const Icon = ICON[link.type];
  const linked = linkedOption(link);

  return (
    <div className="rounded-xl border border-white/[0.08] bg-surface/60 p-5 backdrop-blur-sm">
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-start gap-3">
          <span className="mt-0.5 flex size-8 shrink-0 items-center justify-center rounded-lg border border-white/[0.08] bg-white/[0.03] text-ink-muted">
            <Icon className="size-4" />
          </span>
          <div className="space-y-0.5">
            <p className="text-sm font-medium text-ink">{meta.name}</p>
            <p className="text-xs text-ink-faint">{meta.noun}</p>
          </div>
        </div>

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
              Ressources {meta.name} découvertes
            </DropdownMenuLabel>
            <DropdownMenuRadioGroup
              value={link.linkedId ?? ""}
              onValueChange={(value) => onChange(link.type, value)}
            >
              {link.options.map((option) => (
                <DropdownMenuRadioItem
                  key={option.id}
                  value={option.id}
                  className="flex-col items-start gap-0.5 py-2"
                >
                  <span className="text-xs font-medium text-ink">
                    {option.label}
                  </span>
                  <span className="font-mono text-2xs text-ink-faint">
                    {option.id}
                  </span>
                  <span className="text-2xs text-ink-faint">
                    via {option.identityEmail}
                  </span>
                </DropdownMenuRadioItem>
              ))}
            </DropdownMenuRadioGroup>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>

      <div className="mt-4 border-t border-white/[0.06] pt-3">
        {linked ? (
          <div className="space-y-1">
            <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
              <span className="text-sm font-medium text-ink">
                {linked.label}
              </span>
              <span className="font-mono text-2xs text-ink-muted">
                {linked.id}
              </span>
            </div>
            <p className="text-xs text-ink-muted">via {linked.identityEmail}</p>
          </div>
        ) : (
          <p className="text-xs text-ink-muted">Aucune ressource assignée.</p>
        )}
      </div>
    </div>
  );
}
