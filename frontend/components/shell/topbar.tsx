"use client";

import { Play, Search } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Kbd } from "@/components/ui/kbd";
import { Separator } from "@/components/ui/separator";
import { SidebarTrigger } from "@/components/ui/sidebar";
import { useShell } from "@/lib/shell/shell-context";

import { AppBreadcrumb } from "./app-breadcrumb";

export function Topbar() {
  const { setCommandOpen, workspace } = useShell();

  return (
    <header className="sticky top-0 z-20 flex h-[52px] shrink-0 items-center gap-2 border-b border-hairline bg-canvas/80 px-3 backdrop-blur-sm">
      <SidebarTrigger className="text-ink-muted hover:text-ink" />
      <Separator
        orientation="vertical"
        className="mr-1 !h-4 bg-hairline-strong"
      />
      <AppBreadcrumb />

      <div className="ml-auto flex items-center gap-2">
        <button
          type="button"
          onClick={() => setCommandOpen(true)}
          className="hidden items-center gap-2 rounded-md border border-hairline bg-white/[0.03] py-1 pr-1.5 pl-2 text-xs text-ink-faint transition-colors hover:border-hairline-strong hover:text-ink-muted sm:flex"
        >
          <Search className="size-3.5" />
          <span>Rechercher</span>
          <Kbd className="ml-2">⌘K</Kbd>
        </button>

        <Button
          size="sm"
          onClick={() =>
            toast("Diagnostic lancé", {
              description: `Analyse de ${workspace.domain} en file d'attente.`,
            })
          }
        >
          <Play className="size-3.5" />
          Lancer un diagnostic
        </Button>
      </div>
    </header>
  );
}
