import { humanizeCode, requirementLabel } from "../api/labels";
import { plural } from "../lib/format";
import type { IssueDetailView, ProofHistoryItem } from "../types";
import { EvidenceImage } from "./EvidenceImage";
import { KeyValue } from "./KeyValue";
import { Points } from "./Points";
import { ProvenanceTag } from "./ProvenanceTag";
import { StatusBadge } from "./StatusBadge";
import { Timestamp } from "./Timestamp";

export function ProofPair({ beforeId, afterId, jobId, beforeObservedAt, afterObservedAt }: { beforeId: string | null; afterId: string | null; jobId: string | null; beforeObservedAt?: string | null; afterObservedAt?: string | null }) {
  return (
    <div className="proof-pair">
      {beforeId ? <EvidenceImage evidenceId={beforeId} role="Before" observedAt={beforeObservedAt ?? undefined} jobId={jobId} /> : <p className="muted">No before photo</p>}
      {afterId ? <EvidenceImage evidenceId={afterId} role="After" observedAt={afterObservedAt ?? undefined} jobId={jobId} /> : <p className="muted">No after photo</p>}
    </div>
  );
}

// The official service record's `conflict` field is "none" | "pending" | "disputed"
// (src/agent/models.py CONFLICT_STATES); a disputed record means the operator confirmed
// the dispute and the service match still credits points, so both a "disputed" state and
// any legacy "confirmed"-style value read the same sentence.
function conflictText(state: string | null | undefined): string {
  if (!state) return "No official record conflict";
  const upper = state.toUpperCase();
  if (upper === "DISPUTED" || upper.includes("CONFIRM")) return "Dispute confirmed, service match credited";
  if (upper === "PENDING" || upper.includes("PENDING")) return "Conflict pending, 0 points credited";
  return humanizeCode(state);
}

export function EvidenceComparison({ detail }: { detail: IssueDetailView }) {
  const sources = detail.sources.items; const facts = detail.facts; const record = detail.service_records.items[0] ?? null;
  const completed = facts.official_completed_at ?? record?.completed_at ?? null;
  const newer = completed ? sources.filter((s) => s.observed_at && s.observed_at > completed) : [];
  const history = detail.evidence.history?.items ?? [];
  const ordered = [...history].sort((a, b) => a.submitted_at.localeCompare(b.submitted_at));
  const beforeId = detail.evidence.original_before_evidence_id;
  const jobId = detail.current.job?.id ?? null;
  const accepted = ordered.find((item) => item.submission_id === detail.evidence.accepted_submission_id) ?? null;
  const latest = accepted ?? ordered.at(-1) ?? null;
  const earlier = latest ? ordered.filter((item) => item.submission_id !== latest.submission_id) : ordered;
  const initialId = beforeId ?? sources.flatMap((source) => source.evidence_ids)[0] ?? null;
  const proofCaption = (item: ProofHistoryItem) => <>
    {item.total !== null && item.total !== undefined && <Points value={item.total} threshold={95} style="of" suffix="for payment" />}
    {item.unmet.map((u) => <StatusBadge key={u} label={`Failed: ${requirementLabel(u)}`} tone="attention" />)}
    {item.submission_id === detail.evidence.accepted_submission_id ? <StatusBadge label="Accepted" tone="resolved" /> : item.verification_id && item.unmet.length > 0 ? <StatusBadge label={item.submission_id === latest?.submission_id ? "Verification failed" : "Superseded"} tone={item.submission_id === latest?.submission_id ? "attention" : "neutral"} /> : null}
  </>;
  return (
    <div className="evidence-comparison stack-6">
      {initialId && <div className="evidence-comparison__primary">
        <EvidenceImage evidenceId={initialId} role={beforeId ? "Before" : "Initial evidence"} jobId={jobId} />
        {latest?.after_evidence_id && <EvidenceImage evidenceId={latest.after_evidence_id} role={accepted ? "Accepted after" : "Latest proof"} observedAt={latest.submitted_at} jobId={jobId} caption={proofCaption(latest)} />}
      </div>}
      <div className="official-compare">
        <div className="official-compare__col">
          <h3>Official 311 record</h3>
          {record || facts.official_record_status ? (
            <KeyValue items={[
              { label: "Status", value: facts.official_record_status ?? record?.status ?? "Unknown" },
              { label: "Completed", value: <Timestamp value={completed} /> },
              { label: "Lookup", value: record ? <span>{record.source_mode} <ProvenanceTag provenance={record.provenance} /></span> : "Unknown" },
              { label: "Conflict", value: conflictText(facts.official_conflict_state) },
            ]} />
          ) : <p className="muted">No official record found</p>}
        </div>
        <div className="official-compare__col">
          <h3>Newer observations</h3>
          {newer.length === 0 ? <p className="muted">None newer than the official completion</p> : (
            <ul className="stack-2">{newer.map((s) => <li key={s.id} className="row"><strong>{humanizeCode(s.source_role)}</strong><Timestamp value={s.observed_at} label="observed" /><ProvenanceTag provenance={s.provenance} /></li>)}</ul>
          )}
        </div>
      </div>
      {earlier.some((item) => item.after_evidence_id) && <section className="evidence-comparison__earlier">
        <h3>Earlier proof</h3>
        <div className="proof-row">{earlier.map((item) => item.after_evidence_id && <EvidenceImage key={item.submission_id} evidenceId={item.after_evidence_id} role="Middle proof" observedAt={item.submitted_at} jobId={jobId} caption={proofCaption(item)} />)}</div>
      </section>}
      <details className="evidence-comparison__sources">
        <summary>{plural(sources.length, "observation")}, {detail.issue.components.independent_sources} independent points</summary>
        <ul className="source-list">
          {sources.map((s) => (
            <li key={s.id} className="source-row">
              <div className="row"><strong>{humanizeCode(s.source_role)}</strong><ProvenanceTag provenance={s.provenance} /><Timestamp value={s.observed_at} label="observed" /><Timestamp value={s.received_at} label="received" /></div>
              <p className="small muted">{s.reported_location}</p>
              {s.evidence_ids.length > 0 && <div className="row">{s.evidence_ids.map((id) => <EvidenceImage key={id} evidenceId={id} role="Intake" observedAt={s.observed_at} provenance={s.provenance} size="thumb" />)}</div>}
            </li>
          ))}
        </ul>
      </details>
    </div>
  );
}
