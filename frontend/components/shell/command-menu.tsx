"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { ArrowLeftRight, Play, Plug } from "lucide-react";
import { toast } from "sonner";

import {
  CommandDialog,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
  CommandSeparator,
} from "@/components/ui/command";
import { MOCK_WORKSPACES } from "@/lib/mock/workspaces";
import { NAV_ROUTES } from "@/lib/shell/routes";
import { useShell } from "@/lib/shell/shell-context";

export function CommandMenu() {
  const router = useRouter();
  const { commandOpen, setCommandOpen, setActiveWorkspace, workspace } =
    useShell();

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "k" && (e.metaKey || e.ctrlKey)) {
        e.preventDefault();
        setCommandOpen(!commandOpen);
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [commandOpen, setCommandOpen]);

  function run(action: () => void) {
    setCommandOpen(false);
    action();
  }

  return (
    <CommandDialog
      open={commandOpen}
      onOpenChange={setCommandOpen}
      title="Palette de commandes"
      description="Naviguer et lancer des actions"
    >
      <CommandInput placeholder="Rechercher une page ou une action…" />
      <CommandList>
        <CommandEmpty>Aucun résultat.</CommandEmpty>

        <CommandGroup heading="Aller à">
          {NAV_ROUTES.map((route) => (
            <CommandItem
              key={route.href}
              value={`aller ${route.label}`}
              onSelect={() => run(() => router.push(route.href))}
            >
              <route.icon className="size-4 text-ink-muted" />
              {route.label}
            </CommandItem>
          ))}
        </CommandGroup>

        <CommandSeparator />

        <CommandGroup heading="Actions">
          <CommandItem
            value="lancer un diagnostic"
            onSelect={() =>
              run(() =>
                toast("Diagnostic lancé", {
                  description: `Analyse de ${workspace.domain} en file d'attente.`,
                }),
              )
            }
          >
            <Play className="size-4 text-ink-muted" />
            Lancer un diagnostic
          </CommandItem>
          <CommandItem
            value="voir les connexions google"
            onSelect={() => run(() => router.push("/connections"))}
          >
            <Plug className="size-4 text-ink-muted" />
            Voir les connexions Google
          </CommandItem>
        </CommandGroup>

        <CommandSeparator />

        <CommandGroup heading="Changer d'espace">
          {MOCK_WORKSPACES.map((ws) => (
            <CommandItem
              key={ws.id}
              value={`espace ${ws.name} ${ws.domain}`}
              onSelect={() => run(() => setActiveWorkspace(ws.id))}
            >
              <ArrowLeftRight className="size-4 text-ink-muted" />
              <span className="flex-1">{ws.name}</span>
              <span className="text-2xs text-ink-faint">{ws.domain}</span>
            </CommandItem>
          ))}
        </CommandGroup>
      </CommandList>
    </CommandDialog>
  );
}
