"use client";

import { useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { requestPasswordReset } from "@/lib/api/password-reset";
import { ApiError } from "@/lib/api/client";

export default function ForgotPasswordPage() {
  const [email, setEmail] = useState("");
  const [loading, setLoading] = useState(false);
  const [sent, setSent] = useState(false);

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault();
    setLoading(true);
    try {
      await requestPasswordReset(email);
      // Le backend renvoie toujours un succès, que l'email existe ou non
      // (pour ne jamais révéler l'existence d'un compte) : on affiche donc
      // systématiquement le même message générique, jamais un succès/échec
      // qui dépendrait de la réponse.
      setSent(true);
    } catch (error) {
      toast.error(error instanceof ApiError ? error.message : "Envoi impossible pour le moment");
    } finally {
      setLoading(false);
    }
  }

  if (sent) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-canvas px-4">
        <div className="w-full max-w-sm space-y-4 rounded-xl border border-hairline bg-surface/60 p-6 text-center">
          <h1 className="text-lg font-medium text-ink">Vérifie tes emails</h1>
          <p className="text-sm text-ink-muted">
            Si un compte existe avec cet email, un lien de réinitialisation vient d&apos;être
            envoyé.
          </p>
          <a href="/login" className="block text-center text-xs text-ink-muted hover:text-ink">
            Retour à la connexion
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
        <h1 className="text-lg font-medium text-ink">Mot de passe oublié</h1>
        <p className="text-sm text-ink-muted">
          Indique ton email, on t&apos;envoie un lien pour choisir un nouveau mot de passe.
        </p>
        <Input
          type="email"
          required
          autoComplete="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          placeholder="Email"
        />
        <Button type="submit" disabled={loading} className="w-full">
          {loading ? "Envoi…" : "Envoyer le lien"}
        </Button>
        <a href="/login" className="block text-center text-xs text-ink-muted hover:text-ink">
          Retour à la connexion
        </a>
      </form>
    </div>
  );
}
