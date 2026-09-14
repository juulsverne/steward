import type { ReactNode } from "react";
export function KeyValue({ items }: { items: Array<{ label: string; value: ReactNode }> }) {
  return <dl className="kv">{items.map((it) => <div key={it.label} className="kv__row"><dt>{it.label}</dt><dd>{it.value}</dd></div>)}</dl>;
}
