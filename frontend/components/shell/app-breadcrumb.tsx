"use client";

import { usePathname } from "next/navigation";

import {
  Breadcrumb,
  BreadcrumbItem,
  BreadcrumbList,
  BreadcrumbPage,
  BreadcrumbSeparator,
} from "@/components/ui/breadcrumb";
import { routeForPath } from "@/lib/shell/routes";
import { useShell } from "@/lib/shell/shell-context";

export function AppBreadcrumb() {
  const pathname = usePathname();
  const { workspace } = useShell();
  const route = routeForPath(pathname);

  return (
    <Breadcrumb>
      <BreadcrumbList className="flex-nowrap gap-1.5 text-xs sm:gap-1.5">
        <BreadcrumbItem className="hidden text-ink-faint sm:inline-flex">
          {workspace.name}
        </BreadcrumbItem>
        {route && (
          <>
            <BreadcrumbSeparator className="hidden text-ink-faint sm:block" />
            <BreadcrumbItem>
              <BreadcrumbPage className="truncate text-ink">
                {route.crumb}
              </BreadcrumbPage>
            </BreadcrumbItem>
          </>
        )}
      </BreadcrumbList>
    </Breadcrumb>
  );
}
