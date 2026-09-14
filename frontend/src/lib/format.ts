const dollars = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" });
const stamp = new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric", year: "numeric", hour: "numeric", minute: "2-digit", timeZoneName: "short" });
const clock = new Intl.DateTimeFormat("en-US", { hour: "numeric", minute: "2-digit", timeZoneName: "short" });

export function money(cents: number): string { return dollars.format(cents / 100); }
export function formatTimestamp(iso: string | null | undefined): string {
  if (!iso) return "Unknown";
  const d = new Date(iso); return Number.isNaN(d.getTime()) ? "Unknown" : stamp.format(d);
}
export function pointsText(value: number, threshold: number, style: "needed" | "of"): string {
  return style === "of" ? `${value} of ${threshold}` : `${value} points, ${threshold} needed`;
}
export function plural(n: number, noun: string, pluralNoun?: string): string { return `${n} ${n === 1 ? noun : pluralNoun ?? `${noun}s`}`; }
export function relativeAsOf(iso: string): string { const d = new Date(iso); return Number.isNaN(d.getTime()) ? "as of unknown time" : `as of ${clock.format(d)}`; }
