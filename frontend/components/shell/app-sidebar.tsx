import { Radar } from "lucide-react";

import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarHeader,
  SidebarRail,
  SidebarSeparator,
} from "@/components/ui/sidebar";

import { NavMain } from "./nav-main";
import { TokenHealth } from "./token-health";
import { WorkspaceSwitcher } from "./workspace-switcher";

export function AppSidebar() {
  return (
    <Sidebar collapsible="icon" className="border-hairline">
      <SidebarHeader className="gap-2">
        <div className="flex items-center gap-2 px-1.5 pt-1 text-ink group-data-[collapsible=icon]:justify-center group-data-[collapsible=icon]:px-0">
          <span className="flex size-6 shrink-0 items-center justify-center rounded-md bg-indigo/15 text-indigo">
            <Radar className="size-3.5" />
          </span>
          <span className="text-sm font-semibold tracking-tight group-data-[collapsible=icon]:hidden">
            Control Center
          </span>
        </div>
        <WorkspaceSwitcher />
      </SidebarHeader>

      <SidebarContent>
        <NavMain />
      </SidebarContent>

      <SidebarFooter>
        <SidebarSeparator className="mx-0 bg-hairline" />
        <TokenHealth />
      </SidebarFooter>

      <SidebarRail />
    </Sidebar>
  );
}
