"use client";

import {
  Archive,
  Check,
  ChevronsUpDown,
  Layers,
  MoreHorizontal,
  Plus,
  ShieldCheck,
} from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuSub,
  DropdownMenuSubContent,
  DropdownMenuSubTrigger,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  useSidebar,
} from "@/components/ui/sidebar";
import { archiveWebsite, checkSsl } from "@/lib/api/websites";
import type { SslStatus, Workspace } from "@/lib/mock/types";
import { useShell } from "@/lib/shell/shell-context";
import { cn } from "@/lib/utils";

import { AddWebsiteDialog } from "./add-website-dialog";
import { StackBadge } from "./stack-badge";
import { StackPickerDialog } from "./stack-picker-dialog";
import { StatusDot } from "./status-dot";

const SSL_BAD: SslStatus[] = [
  "expired",
  "expiring_soon",
  "self_signed",
  "hostname_mismatch",
  "untrusted",
];

const SSL_LABEL: Record<string, string> = {
  expired: "certificat HTTPS expiré",
  expiring_soon: "certificat HTTPS bientôt expiré",
  self_signed: "certificat auto-signé",
  hostname_mismatch: "certificat : nom de domaine incorrect",
  untrusted: "certificat non fiable",
  unreachable: "site injoignable",
};

async function runSslCheck(
  domain: string,
  websiteId: string,
  apply: (patch: Partial<Workspace>) => void,
) {
  const toastId = toast.loading(`Vérification du certificat de ${domain}…`);
  try {
    const ssl = await checkSsl(websiteId);
    apply({
      sslStatus: (ssl.status ?? null) as SslStatus | null,
      sslExpiresAt: ssl.expires_at,
    });
    const ok = ssl.status === "valid";
    toast[ok ? "success" : "warning"](
      ok
        ? "Certificat valide"
        : (SSL_LABEL[ssl.status ?? ""] ?? "Certificat à vérifier"),
      {
        id: toastId,
        description: ssl.expires_at
          ? `Expire le ${ssl.expires_at.slice(0, 10)}`
          : undefined,
      },
    );
  } catch {
    toast.error("Vérification impossible", { id: toastId });
  }
}

export function WorkspaceSwitcher() {
  const {
    workspace,
    workspaces,
    setActiveWorkspace,
    updateWorkspace,
    removeWorkspace,
  } = useShell();
  const { isMobile } = useSidebar();
  const [addOpen, setAddOpen] = useState(false);
  const [stackFor, setStackFor] = useState<string | null>(null);

  const sslWarning =
    workspace.sslStatus && SSL_BAD.includes(workspace.sslStatus)
      ? SSL_LABEL[workspace.sslStatus]
      : null;

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
                    label={workspace.stackLabel}
                    className="group-data-[collapsible=icon]:hidden"
                  />
                </span>
                <span className="flex items-center gap-1.5 truncate text-2xs text-ink-faint">
                  {sslWarning && (
                    <span
                      className="size-1.5 shrink-0 rounded-full bg-danger"
                      title={sslWarning}
                    />
                  )}
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
            className="w-72"
          >
            <DropdownMenuLabel className="text-2xs text-ink-faint">
              Sites suivis
            </DropdownMenuLabel>
            {workspaces.map((ws) => {
              const wid = ws.websiteId;
              const bad = ws.sslStatus ? SSL_BAD.includes(ws.sslStatus) : false;
              return (
                <div key={ws.id} className="flex items-center">
                  <DropdownMenuItem
                    onSelect={() => setActiveWorkspace(ws.id)}
                    className="flex-1 gap-2"
                  >
                    <StatusDot status={ws.tokenStatus} />
                    <span className="flex-1 truncate text-sm">{ws.name}</span>
                    {bad && (
                      <span
                        className="size-1.5 shrink-0 rounded-full bg-danger"
                        title={SSL_LABEL[ws.sslStatus ?? ""]}
                      />
                    )}
                    <StackBadge stack={ws.stack} label={ws.stackLabel} />
                    <Check
                      className={cn(
                        "size-3.5 text-ink",
                        ws.id === workspace.id ? "opacity-100" : "opacity-0",
                      )}
                    />
                  </DropdownMenuItem>

                  {wid && (
                    <DropdownMenuSub>
                      <DropdownMenuSubTrigger className="rounded-md px-1.5 py-1.5 [&>svg:last-child]:hidden">
                        <MoreHorizontal className="size-3.5 text-ink-faint" />
                      </DropdownMenuSubTrigger>
                      <DropdownMenuSubContent className="w-52">
                        <DropdownMenuItem
                          onSelect={(event) => {
                            event.preventDefault();
                            setStackFor(wid);
                          }}
                          className="gap-2 text-xs"
                        >
                          <Layers className="size-3.5" />
                          Confirmer la stack
                        </DropdownMenuItem>
                        <DropdownMenuItem
                          onSelect={() =>
                            void runSslCheck(ws.domain, wid, (patch) =>
                              updateWorkspace(ws.id, patch),
                            )
                          }
                          className="gap-2 text-xs"
                        >
                          <ShieldCheck className="size-3.5" />
                          Vérifier le certificat SSL
                        </DropdownMenuItem>
                        <DropdownMenuSeparator />
                        <DropdownMenuItem
                          onSelect={() => {
                            void archiveWebsite(wid)
                              .then(() => {
                                removeWorkspace(ws.id);
                                toast(`${ws.name} archivé`, {
                                  description:
                                    "Le site n'apparaît plus dans la liste.",
                                });
                              })
                              .catch(() =>
                                toast.error("Archivage impossible."),
                              );
                          }}
                          className="gap-2 text-xs text-danger focus:text-danger"
                        >
                          <Archive className="size-3.5" />
                          Archiver le site
                        </DropdownMenuItem>
                      </DropdownMenuSubContent>
                    </DropdownMenuSub>
                  )}
                </div>
              );
            })}
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

      <AddWebsiteDialog
        open={addOpen}
        onOpenChange={setAddOpen}
        onNeedsStackConfirmation={setStackFor}
      />
      <StackPickerDialog
        websiteId={stackFor}
        open={stackFor !== null}
        onOpenChange={(next) => {
          if (!next) setStackFor(null);
        }}
      />
    </SidebarMenu>
  );
}
