import { pointsText } from "../lib/format";
export function Points({ value, threshold, style = "needed", suffix }: { value: number; threshold: number; style?: "needed" | "of"; suffix?: string }) {
  return <span className="tabular points">{pointsText(value, threshold, style)}{suffix ? ` ${suffix}` : ""}</span>;
}
