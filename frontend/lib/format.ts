/** Deterministic, compact "il y a 2h" from a plain hours-ago number. */
export function relativeHours(hours: number): string {
  if (hours < 1) return "à l'instant";
  if (hours < 24) return `il y a ${hours}h`;
  const days = Math.round(hours / 24);
  if (days === 1) return "hier";
  if (days < 30) return `il y a ${days}j`;
  return `il y a ${Math.round(days / 30)} mois`;
}

/** "+3 pts" / "−4 pts" / "stable" */
export function formatDelta(delta: number): string {
  if (delta === 0) return "stable";
  const sign = delta > 0 ? "+" : "−";
  return `${sign}${Math.abs(delta)} pts`;
}
