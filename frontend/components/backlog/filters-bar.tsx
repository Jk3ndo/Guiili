"use client";

import { ChevronDown, Search } from "lucide-react";

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import {
  CATEGORY_LABEL,
  SEVERITY_LABEL,
  type IssueCategory,
  type IssueSeverity,
} from "@/lib/mock/backlog";
import { cn } from "@/lib/utils";

export interface BacklogFilters {
  query: string;
  category: IssueCategory | "all";
  severity: IssueSeverity | "all";
}

const CATEGORIES = Object.keys(CATEGORY_LABEL) as IssueCategory[];
const SEVERITIES = Object.keys(SEVERITY_LABEL) as IssueSeverity[];

function FilterMenu<T extends string>({
  label,
  value,
  labels,
  options,
  onChange,
}: {
  label: string;
  value: T | "all";
  labels: Record<T, string>;
  options: T[];
  onChange: (value: T | "all") => void;
}) {
  const active = value !== "all";

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <button
          type="button"
          className={cn(
            "inline-flex h-9 shrink-0 items-center gap-1.5 rounded-lg border px-3 text-xs font-medium shadow-sm transition-colors",
            active
              ? "border-white/[0.14] bg-white/[0.06] text-ink"
              : "border-white/[0.08] bg-white/[0.03] text-ink-muted hover:bg-white/[0.06] hover:text-ink",
          )}
        >
          {active ? labels[value as T] : label}
          <ChevronDown className="size-3.5" />
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-44">
        <DropdownMenuRadioGroup
          value={value}
          onValueChange={(next) => onChange(next as T | "all")}
        >
          <DropdownMenuRadioItem value="all">Toutes</DropdownMenuRadioItem>
          {options.map((option) => (
            <DropdownMenuRadioItem key={option} value={option}>
              {labels[option]}
            </DropdownMenuRadioItem>
          ))}
        </DropdownMenuRadioGroup>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

export function FiltersBar({
  filters,
  onChange,
}: {
  filters: BacklogFilters;
  onChange: (filters: BacklogFilters) => void;
}) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      <div className="relative w-full sm:max-w-64">
        <Search className="pointer-events-none absolute top-1/2 left-2.5 size-3.5 -translate-y-1/2 text-ink-faint" />
        <Input
          type="search"
          value={filters.query}
          onChange={(event) =>
            onChange({ ...filters, query: event.target.value })
          }
          placeholder="Rechercher un correctif"
          className="h-9 rounded-lg pl-8 text-xs"
        />
      </div>

      <FilterMenu
        label="Catégorie"
        value={filters.category}
        labels={CATEGORY_LABEL}
        options={CATEGORIES}
        onChange={(category) => onChange({ ...filters, category })}
      />
      <FilterMenu
        label="Sévérité"
        value={filters.severity}
        labels={SEVERITY_LABEL}
        options={SEVERITIES}
        onChange={(severity) => onChange({ ...filters, severity })}
      />
    </div>
  );
}
