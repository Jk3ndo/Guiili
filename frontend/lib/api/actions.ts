import { toast } from "sonner";

import { apiDownload, apiPost, apiPostSlow, saveBlob } from "./client";
import { notifyDemoMode } from "./demo";
import type { GtmHeadlessDto, ScanDto } from "./dto";
import { emitDiagnosticComplete } from "./events";
import { describeMeasurementError, HEADLESS_TIMEOUT_MS } from "./measurement";
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
 *  Deploye, le navigateur tourne sur le service worker (jusqu'a ~150 s avec le
 *  demarrage a froid) : delai client de 180 s. Un delai depasse, un 5xx, un 429 ou
 *  un echec du navigateur ne sont JAMAIS une API hors ligne : message clair, pas de
 *  mode demo (reserve au site inconnu du backend). */
export async function verifyGtmHeadless(domain: string): Promise<boolean> {
  let websiteId: string;
  try {
    websiteId = await resolveWebsiteId(domain);
  } catch {
    notifyDemoMode();
    return false;
  }
  try {
    const result = await apiPostSlow<GtmHeadlessDto>(
      `/websites/${websiteId}/gtm/headless`,
      undefined,
      HEADLESS_TIMEOUT_MS,
    );
    if (result.error) {
      // Le code brut (`headless_failed`) ne s'affiche jamais : l'échec du navigateur
      // n'a pas modifié la dernière vérification réussie.
      toast.error("Vérification impossible", {
        description:
          "La vérification en conditions réelles n'a pas pu s'exécuter, réessaie dans un instant.",
      });
      return false;
    }
    toast.success("Vérification headless terminée", {
      description: result.gtm_js_loaded
        ? "GTM se charge bien dans un vrai navigateur."
        : "GTM ne s'est pas chargé — voir les nouveaux résultats.",
    });
    emitDiagnosticComplete();
    return true;
  } catch (error) {
    toast.error("Vérification impossible", {
      description: describeMeasurementError(error),
    });
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
