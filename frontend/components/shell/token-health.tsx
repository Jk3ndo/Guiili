"use client";

import Link from "next/link";

import {
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
} from "@/components/ui/sidebar";
import { useShell } from "@/lib/shell/shell-context";

import { StatusDot } from "./status-dot";

const LABEL: Record<string, string> = {
  connected: "Connecté",
  needs_reauth: "Reauth requise",
};

export function TokenHealth() {
  const { workspace } = useShell();
  const label = LABEL[workspace.tokenStatus];

  return (
    <SidebarMenu>
      <SidebarMenuItem>
        <SidebarMenuButton
          asChild
          tooltip={`Connexions Google — ${label}`}
          className="text-ink-muted hover:text-ink"
        >
          <Link href="/connections">
            <StatusDot status={workspace.tokenStatus} />
            <span className="flex-1 truncate text-xs">Tokens Google</span>
            <span className="text-2xs text-ink-faint group-data-[collapsible=icon]:hidden">
              {label}
            </span>
          </Link>
        </SidebarMenuButton>
      </SidebarMenuItem>
    </SidebarMenu>
  );
}
