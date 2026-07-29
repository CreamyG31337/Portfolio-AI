/**
 * Shared bullish / bearish / neutral chip colors (Insights page is the reference).
 * Soft tint + colored text + light border — not solid fills with white text.
 */

/** Color / border classes only (compose with size utilities in the template). */
export function sentimentToneClasses(value: string | null | undefined): string {
  const v = (value || "").toLowerCase();
  if (v.includes("bull")) return "bg-green-500/10 text-green-500 border-green-500/30";
  if (v.includes("bear")) return "bg-red-500/10 text-red-500 border-red-500/30";
  return "bg-amber-500/10 text-amber-600 border-amber-500/30";
}

/**
 * Full chip class string for programmatic badges
 * (AI analysis, watchlist stance, momentum bias, etc.).
 */
export function sentimentBadgeClasses(value: string | null | undefined): string {
  return `px-2 py-0.5 text-xs font-semibold rounded border inline-flex items-center ${sentimentToneClasses(value)}`;
}
