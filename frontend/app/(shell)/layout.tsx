import { cookies } from "next/headers";

import { AppSidebar } from "@/components/shell/app-sidebar";
import { CommandMenu } from "@/components/shell/command-menu";
import { Topbar } from "@/components/shell/topbar";
import { SidebarInset, SidebarProvider } from "@/components/ui/sidebar";
import { Toaster } from "@/components/ui/sonner";
import { getWorkspace } from "@/lib/mock/workspaces";
import { ShellProvider, WORKSPACE_COOKIE } from "@/lib/shell/shell-context";

export default async function ShellLayout({ children }: LayoutProps<"/">) {
  const cookieStore = await cookies();
  const defaultOpen = cookieStore.get("sidebar_state")?.value !== "false";
  const initialWorkspaceId = getWorkspace(
    cookieStore.get(WORKSPACE_COOKIE)?.value ?? "",
  ).id;

  return (
    <ShellProvider initialWorkspaceId={initialWorkspaceId}>
      <SidebarProvider defaultOpen={defaultOpen}>
        <AppSidebar />
        <SidebarInset className="min-w-0 bg-canvas">
          <Topbar />
          <main className="flex-1 overflow-y-auto">{children}</main>
        </SidebarInset>
        <CommandMenu />
        <Toaster position="bottom-right" />
      </SidebarProvider>
    </ShellProvider>
  );
}
