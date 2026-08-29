"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import {
  SidebarGroup,
  SidebarGroupLabel,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
} from "@/components/ui/sidebar";
import { NAV_ROUTES, routeForPath } from "@/lib/shell/routes";
import { cn } from "@/lib/utils";

export function NavMain() {
  const pathname = usePathname();
  const active = routeForPath(pathname);

  return (
    <SidebarGroup>
      <SidebarGroupLabel className="text-2xs tracking-wide text-ink-faint">
        Pilotage
      </SidebarGroupLabel>
      <SidebarMenu>
        {NAV_ROUTES.map((route) => {
          const isActive = active?.href === route.href;
          return (
            <SidebarMenuItem key={route.href}>
              <SidebarMenuButton
                asChild
                isActive={isActive}
                tooltip={route.label}
                className={cn(
                  "relative text-ink-muted transition-colors",
                  "hover:text-ink data-[active=true]:font-medium data-[active=true]:text-ink",
                  "data-[active=true]:before:absolute data-[active=true]:before:top-1/2 data-[active=true]:before:left-0 data-[active=true]:before:h-4 data-[active=true]:before:w-0.5 data-[active=true]:before:-translate-y-1/2 data-[active=true]:before:rounded-full data-[active=true]:before:bg-ink",
                )}
              >
                <Link href={route.href}>
                  <route.icon className="size-4" />
                  <span>{route.label}</span>
                </Link>
              </SidebarMenuButton>
            </SidebarMenuItem>
          );
        })}
      </SidebarMenu>
    </SidebarGroup>
  );
}
