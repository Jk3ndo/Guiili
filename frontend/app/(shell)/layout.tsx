import { cookies } from "next/headers";
import { redirect } from "next/navigation";

import { AppSidebar } from "@/components/shell/app-sidebar";
import { CommandMenu } from "@/components/shell/command-menu";
import { Topbar } from "@/components/shell/topbar";
import { SidebarInset, SidebarProvider } from "@/components/ui/sidebar";
import { fetchMeServer } from "@/lib/api/auth";
import { ShellProvider, WORKSPACE_COOKIE } from "@/lib/shell/shell-context";

export default async function ShellLayout({ children }: LayoutProps<"/">) {
  const cookieStore = await cookies();

  const me = await fetchMeServer(cookieStore.toString());
  if (me === null) redirect("/login");

  const defaultOpen = cookieStore.get("sidebar_state")?.value !== "false";
  // Simple indice pour le premier rendu client : ShellProvider recale sur un
  // vrai site (ou l'écran "aucun site") une fois `listWebsites()` chargé.
  const initialWorkspaceId = cookieStore.get(WORKSPACE_COOKIE)?.value ?? "";

  return (
    <ShellProvider initialWorkspaceId={initialWorkspaceId}>
      <SidebarProvider defaultOpen={defaultOpen}>
        <AppSidebar />
        <SidebarInset className="min-w-0 bg-canvas">
          <Topbar me={me} />
          <main className="flex-1 overflow-y-auto">{children}</main>
        </SidebarInset>
        <CommandMenu />
      </SidebarProvider>
    </ShellProvider>
  );
}
