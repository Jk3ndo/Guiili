/** Texte libre venu d'un service externe : tronqué avant affichage (jamais interprété comme du HTML). */
export function truncate(text: string, max = 200): string {
  const clean = text.replace(/\s+/g, " ").trim();
  return clean.length > max ? `${clean.slice(0, max - 1)}…` : clean;
}

/** Date et heure en français, ou null si la date est absente ou illisible. */
export function formatDateTime(iso: string | null): string | null {
  if (iso === null) return null;
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return null;
  return date.toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" });
}
