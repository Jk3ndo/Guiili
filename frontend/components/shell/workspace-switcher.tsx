"use client";

import { Check, ChevronsUpDown, Plus } from "lucide-react";
import { useState } from "react";

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  useSidebar,
} from "@/components/ui/sidebar";
import { useShell } from "@/lib/shell/shell-context";
import { cn } from "@/lib/utils";

import { AddWebsiteDialog } from "./add-website-dialog";
import { StackBadge } from "./stack-badge";
import { StatusDot } from "./status-dot";

export function WorkspaceSwitcher() {
  const { workspace, workspaces, setActiveWorkspace } = useShell();
  const { isMobile } = useSidebar();
  const [addOpen, setAddOpen] = useState(false);

  return (
    <SidebarMenu>
      <SidebarMenuItem>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <SidebarMenuButton
              size="lg"
              className="group/ws data-[state=open]:bg-sidebar-accent"
            >
              <span className="flex size-7 shrink-0 items-center justify-center rounded-md border border-hairline-strong bg-raised text-2xs font-semibold text-ink">
                {workspace.name.slice(0, 2).toUpperCase()}
              </span>
              <span className="grid flex-1 text-left leading-tight">
                <span className="flex items-center gap-1.5">
                  <span className="truncate text-sm font-medium text-ink">
                    {workspace.name}
                  </span>
                  <StackBadge
                    stack={workspace.stack}
                    className="group-data-[collapsible=icon]:hidden"
                  />
                </span>
                <span className="truncate text-2xs text-ink-faint">
                  {workspace.domain}
                </span>
              </span>
              <ChevronsUpDown className="ml-auto size-4 shrink-0 text-ink-faint transition-transform group-data-[state=open]/ws:rotate-180" />
            </SidebarMenuButton>
          </DropdownMenuTrigger>
          <DropdownMenuContent
            align="start"
            side={isMobile ? "bottom" : "right"}
            sideOffset={8}
            className="w-64"
          >
            <DropdownMenuLabel className="text-2xs text-ink-faint">
              Sites suivis
            </DropdownMenuLabel>
            {workspaces.map((ws) => (
              <DropdownMenuItem
                key={ws.id}
                onSelect={() => setActiveWorkspace(ws.id)}
                className="gap-2"
              >
                <StatusDot status={ws.tokenStatus} />
                <span className="flex-1 truncate text-sm">{ws.name}</span>
                <StackBadge stack={ws.stack} />
                <Check
                  className={cn(
                    "size-3.5 text-ink",
                    ws.id === workspace.id ? "opacity-100" : "opacity-0",
                  )}
                />
              </DropdownMenuItem>
            ))}
            <DropdownMenuSeparator />
            <DropdownMenuItem
              onSelect={(event) => {
                event.preventDefault();
                setAddOpen(true);
              }}
              className="gap-2 text-ink-muted"
            >
              <Plus className="size-4" />
              Ajouter un domaine
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </SidebarMenuItem>

      <AddWebsiteDialog open={addOpen} onOpenChange={setAddOpen} />
    </SidebarMenu>
  );
}
