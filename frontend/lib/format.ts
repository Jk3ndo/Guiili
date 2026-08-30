/** Deterministic, compact "il y a 2h" from a plain hours-ago number. */
export function relativeHours(hours: number): string {
  if (hours < 1) return "à l'instant";
  if (hours < 24) return `il y a ${hours}h`;
  const days = Math.round(hours / 24);
  if (days === 1) return "hier";
  if (days < 30) return `il y a ${days}j`;
  return `il y a ${Math.round(days / 30)} mois`;
}

/** "hier" / "il y a 4 j" / "il y a 2 mois" from a plain days-ago number. */
export function relativeDays(days: number): string {
  if (days <= 0) return "aujourd'hui";
  if (days === 1) return "hier";
  if (days < 30) return `il y a ${days} j`;
  return `il y a ${Math.round(days / 30)} mois`;
}

/** Compact French count: 48200 → "48,2 k", 412 → "412", 0 → "—". */
export function formatCount(value: number): string {
  if (value <= 0) return "—";
  if (value < 1000) return String(value);
  return new Intl.NumberFormat("fr-FR", {
    notation: "compact",
    maximumFractionDigits: 1,
  }).format(value);
}

/** "+3 pts" / "−4 pts" / "stable" */
export function formatDelta(delta: number): string {
  if (delta === 0) return "stable";
  const sign = delta > 0 ? "+" : "−";
  return `${sign}${Math.abs(delta)} pts`;
}
