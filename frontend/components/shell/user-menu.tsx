"use client";

import { LogOut, UserRound } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { logout, type MeDto } from "@/lib/api/auth";
import { ApiError } from "@/lib/api/client";

export function UserMenu({ me }: { me: MeDto }) {
  const router = useRouter();
  const [loading, setLoading] = useState(false);

  async function onLogout() {
    setLoading(true);
    try {
      await logout();
      router.push("/login");
    } catch (error) {
      toast.error(error instanceof ApiError ? error.message : "Deconnexion impossible");
      setLoading(false);
    }
  }

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <button
          type="button"
          className="inline-flex size-9 items-center justify-center rounded-lg border border-hairline bg-white/[0.03] text-ink-muted transition-colors hover:border-hairline-strong hover:text-ink"
          aria-label="Compte"
        >
          <UserRound className="size-4" />
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-56">
        <DropdownMenuLabel className="truncate">
          {me.display_name || me.email}
        </DropdownMenuLabel>
        {me.display_name && (
          <div className="truncate px-2 pb-1.5 text-xs text-ink-faint">{me.email}</div>
        )}
        <DropdownMenuSeparator />
        <DropdownMenuItem disabled={loading} onSelect={() => void onLogout()}>
          <LogOut className="size-4" />
          Se déconnecter
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
