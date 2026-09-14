import { provenanceTitle } from "../api/labels";
import type { Provenance } from "../types";
export function ProvenanceTag({ provenance }: { provenance: Provenance }) {
  return <span className={`prov prov--${provenance}`} title={provenanceTitle(provenance)}>{provenance}</span>;
}
