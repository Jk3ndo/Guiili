"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { login } from "@/lib/api/auth";
import { ApiError } from "@/lib/api/client";

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault();
    setLoading(true);
    try {
      await login(email, password);
      router.push("/overview");
    } catch (error) {
      toast.error(error instanceof ApiError ? error.message : "Connexion impossible");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-canvas px-4">
      <form
        onSubmit={onSubmit}
        className="w-full max-w-sm space-y-4 rounded-xl border border-hairline bg-surface/60 p-6"
      >
        <h1 className="text-lg font-medium text-ink">Se connecter</h1>
        <Input
          type="email"
          required
          autoComplete="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          placeholder="Email"
        />
        <Input
          type="password"
          required
          autoComplete="current-password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          placeholder="Mot de passe"
        />
        <Button type="submit" disabled={loading} className="w-full">
          {loading ? "Connexion…" : "Se connecter"}
        </Button>
        <a
          href="/login/google"
          className="block text-center text-xs text-ink-muted hover:text-ink"
        >
          Ou continuer avec Google
        </a>
        <a href="/register" className="block text-center text-xs text-ink-muted hover:text-ink">
          Créer un compte
        </a>
        <a
          href="/forgot-password"
          className="block text-center text-xs text-ink-muted hover:text-ink"
        >
          Mot de passe oublié ?
        </a>
      </form>
    </div>
  );
}
