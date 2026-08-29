"use client";

import { ChevronDown } from "lucide-react";

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { STATUS_LABEL, STATUS_ORDER, type IssueStatus } from "@/lib/mock/backlog";
import { cn } from "@/lib/utils";

const DOT: Record<IssueStatus, string> = {
  todo: "bg-warn",
  in_progress: "bg-sky-400",
  done: "bg-ok",
};

const TEXT: Record<IssueStatus, string> = {
  todo: "text-warn",
  in_progress: "text-sky-400",
  done: "text-ok",
};

export function StatusSelect({
  status,
  onChange,
}: {
  status: IssueStatus;
  onChange: (status: IssueStatus) => void;
}) {
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <button
          type="button"
          className="inline-flex h-8 shrink-0 items-center gap-1.5 rounded-lg border border-white/[0.08] bg-white/[0.03] px-2.5 text-xs font-medium shadow-sm transition-colors hover:bg-white/[0.06]"
        >
          <span className={cn("size-1.5 shrink-0 rounded-full", DOT[status])} />
          <span className={TEXT[status]}>{STATUS_LABEL[status]}</span>
          <ChevronDown className="size-3.5 text-ink-faint" />
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-40">
        <DropdownMenuRadioGroup
          value={status}
          onValueChange={(next) => onChange(next as IssueStatus)}
        >
          {STATUS_ORDER.map((option) => (
            <DropdownMenuRadioItem key={option} value={option} className="gap-2">
              <span
                className={cn("size-1.5 shrink-0 rounded-full", DOT[option])}
              />
              {STATUS_LABEL[option]}
            </DropdownMenuRadioItem>
          ))}
        </DropdownMenuRadioGroup>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
