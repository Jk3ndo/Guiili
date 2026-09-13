"use client";

import { Suspense, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { confirmPasswordReset } from "@/lib/api/password-reset";
import { ApiError } from "@/lib/api/client";

function ResetPasswordForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const token = searchParams.get("token");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault();
    if (!token) return;
    setLoading(true);
    try {
      await confirmPasswordReset(token, password);
      toast.success("Mot de passe mis à jour, connecte-toi.");
      router.push("/login");
    } catch (error) {
      // Le token peut être invalide, déjà utilisé ou expiré (400 côté backend) :
      // on ne laisse pas l'utilisateur bloqué, on le renvoie demander un nouveau lien.
      toast.error(
        error instanceof ApiError ? error.message : "Réinitialisation impossible pour le moment",
      );
    } finally {
      setLoading(false);
    }
  }

  if (!token) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-canvas px-4">
        <div className="w-full max-w-sm space-y-4 rounded-xl border border-hairline bg-surface/60 p-6 text-center">
          <h1 className="text-lg font-medium text-ink">Lien invalide</h1>
          <p className="text-sm text-ink-muted">
            Ce lien de réinitialisation est incomplet ou invalide.
          </p>
          <a
            href="/forgot-password"
            className="block text-center text-xs text-ink-muted hover:text-ink"
          >
            Demander un nouveau lien
          </a>
        </div>
      </div>
    );
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-canvas px-4">
      <form
        onSubmit={onSubmit}
        className="w-full max-w-sm space-y-4 rounded-xl border border-hairline bg-surface/60 p-6"
      >
        <h1 className="text-lg font-medium text-ink">Choisir un nouveau mot de passe</h1>
        <Input
          type="password"
          required
          autoComplete="new-password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          placeholder="Nouveau mot de passe"
        />
        <Button type="submit" disabled={loading} className="w-full">
          {loading ? "Mise à jour…" : "Mettre à jour le mot de passe"}
        </Button>
        <a
          href="/forgot-password"
          className="block text-center text-xs text-ink-muted hover:text-ink"
        >
          Demander un nouveau lien
        </a>
      </form>
    </div>
  );
}

export default function ResetPasswordPage() {
  return (
    <Suspense fallback={null}>
      <ResetPasswordForm />
    </Suspense>
  );
}
