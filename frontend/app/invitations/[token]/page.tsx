"use client";

import { use, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { fetchMe } from "@/lib/api/auth";
import { ApiError } from "@/lib/api/client";
import { acceptInvitation, getInvitation, type InvitationDto } from "@/lib/api/invitations";

export default function InvitationPage({ params }: { params: Promise<{ token: string }> }) {
  const { token } = use(params);
  const router = useRouter();
  const [invitation, setInvitation] = useState<InvitationDto | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    void getInvitation(token)
      .then(setInvitation)
      .catch(() => setError("Invitation introuvable ou expirée."));
  }, [token]);

  async function onAccept() {
    setLoading(true);
    try {
      const me = await fetchMe();
      if (me === null) {
        router.push(`/register?invitation=${token}`);
        return;
      }
      await acceptInvitation(token);
      toast.success("Tu as rejoint l'espace.");
      router.push("/overview");
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Impossible d'accepter l'invitation");
    } finally {
      setLoading(false);
    }
  }

  if (error) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-canvas px-4">
        <p className="text-sm text-ink-muted">{error}</p>
      </div>
    );
  }

  if (!invitation) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-canvas px-4">
        <p className="text-sm text-ink-muted">Chargement…</p>
      </div>
    );
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-canvas px-4">
      <div className="w-full max-w-sm space-y-4 rounded-xl border border-hairline bg-surface/60 p-6 text-center">
        <h1 className="text-lg font-medium text-ink">Rejoindre un espace de travail</h1>
        <p className="text-sm text-ink-muted">
          Tu es invité à rejoindre un espace de travail en tant que{" "}
          <span className="text-ink">{invitation.invited_email}</span>.
        </p>
        <Button type="button" disabled={loading} className="w-full" onClick={() => void onAccept()}>
          {loading ? "Connexion…" : "Rejoindre"}
        </Button>
      </div>
    </div>
  );
}
