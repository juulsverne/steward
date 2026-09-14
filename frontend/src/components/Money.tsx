import { money } from "../lib/format";
export function Money({ cents, simulated = false }: { cents: number; simulated?: boolean }) {
  return <span className="tabular money">{money(cents)}{simulated && <span className="muted small"> simulated</span>}</span>;
}
