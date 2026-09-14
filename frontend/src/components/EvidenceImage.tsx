import { useState, type ReactNode } from "react";
import { formatTimestamp } from "../lib/format";
import type { Provenance } from "../types";
import { ProvenanceTag } from "./ProvenanceTag";
import { Timestamp } from "./Timestamp";

export function evidenceUrl(evidenceId: string, jobId?: string | null): string {
  return `/api/evidence/${encodeURIComponent(evidenceId)}/content${jobId ? `?job_id=${encodeURIComponent(jobId)}` : ""}`;
}

export function EvidenceImage({ evidenceId, role, observedAt, provenance, jobId, size = "full", caption }: {
  evidenceId: string; role: string; observedAt?: string | null; provenance?: Provenance | null; jobId?: string | null; size?: "thumb" | "full"; caption?: ReactNode;
}) {
  const [failed, setFailed] = useState(false);
  return (
    <figure className={`evidence evidence--${size}`}>
      {failed ? (
        <div className="evidence__fallback" role="note">Image unavailable <span className="mono small">{evidenceId}</span></div>
      ) : (
        <img src={evidenceUrl(evidenceId, jobId)} alt={`${role} photo, observed ${formatTimestamp(observedAt)}`} loading="lazy" onError={() => setFailed(true)} />
      )}
      <figcaption className="evidence__caption small">
        <span className="evidence__role">{role}</span>
        {observedAt !== undefined && <Timestamp value={observedAt} label="observed" />}
        {provenance && <ProvenanceTag provenance={provenance} />}
        {caption}
      </figcaption>
    </figure>
  );
}
