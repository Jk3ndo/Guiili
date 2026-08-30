import { toast } from "sonner";

let notified = false;

/** Avertit une seule fois par session que l'UI tourne sur les données mockées. */
export function notifyDemoMode(): void {
  if (notified) return;
  notified = true;
  toast("Mode démo — API hors-ligne", {
    description: "Affichage des données de secours mockées.",
  });
}
