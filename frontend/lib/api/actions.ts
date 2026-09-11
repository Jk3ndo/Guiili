import { toast } from "sonner";

import { apiDownload, apiPost, apiPostSlow, saveBlob } from "./client";
import { notifyDemoMode } from "./demo";
import type { GtmHeadlessDto, ScanDto } from "./dto";
import { emitDiagnosticComplete } from "./events";
import { resolveWebsiteId } from "./workspaces";

/** Lance un scan backend pour le site ; retombe sur un toast « démo » sinon. */
export async function runDiagnostic(domain: string): Promise<void> {
  try {
    const websiteId = await resolveWebsiteId(domain);
    const result = await apiPost<ScanDto>(`/websites/${websiteId}/scan`);
    const touched = result.issues.created + result.issues.updated;
    toast.success("Diagnostic exécuté", {
      description: `${domain} — ${touched} anomalie${touched > 1 ? "s" : ""}, stack ${result.detected_stack}`,
    });
    emitDiagnosticComplete();
  } catch {
    notifyDemoMode();
    toast("Diagnostic lancé (mode démo)", {
      description: `Analyse de ${domain} en file d'attente.`,
    });
  }
}

/** Verifie la configuration GTM dans un vrai navigateur (Chromium headless).
 *  Peut prendre jusqu'à ~20 s (navigation + networkidle) ; timeout client 30 s. */
export async function verifyGtmHeadless(domain: string): Promise<boolean> {
  try {
    const websiteId = await resolveWebsiteId(domain);
    const result = await apiPostSlow<GtmHeadlessDto>(
      `/websites/${websiteId}/gtm/headless`,
      undefined,
      30_000,
    );
    if (result.error) {
      toast.error("Vérification impossible", { description: result.error });
      return false;
    }
    toast.success("Vérification headless terminée", {
      description: result.gtm_js_loaded
        ? "GTM se charge bien dans un vrai navigateur."
        : "GTM ne s'est pas chargé — voir les nouveaux résultats.",
    });
    emitDiagnosticComplete();
    return true;
  } catch {
    notifyDemoMode();
    return false;
  }
}

/** Télécharge le vrai conteneur GTM produit par FastAPI. `false` -> l'appelant
 *  doit générer le fichier de secours côté client. */
export async function downloadGtmContainer(
  domain: string,
  mode: "merge" | "overwrite" = "merge",
): Promise<boolean> {
  try {
    const websiteId = await resolveWebsiteId(domain);
    const { blob, filename } = await apiDownload(
      `/websites/${websiteId}/gtm-export?mode=${mode}`,
    );
    saveBlob(blob, filename);
    toast.success("Conteneur GTM téléchargé", { description: filename });
    return true;
  } catch {
    notifyDemoMode();
    return false;
  }
}
