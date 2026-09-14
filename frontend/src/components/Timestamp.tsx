import { formatTimestamp } from "../lib/format";
export function Timestamp({ value, label }: { value: string | null | undefined; label?: string }) {
  return <span className="timestamp tabular">{label && <span className="muted small">{label} </span>}{value ? <time dateTime={value} title={value}>{formatTimestamp(value)}</time> : <span>Unknown</span>}</span>;
}
