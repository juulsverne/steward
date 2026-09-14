import { decisionLabel, humanizeCode, requirementLabel } from "../api/labels";
import type { IssueDetailView } from "../types";
import { EvidenceImage } from "./EvidenceImage";
import { KeyValue } from "./KeyValue";
import { Points } from "./Points";
import { Timestamp } from "./Timestamp";

export function DecisionCard({ detail }: { detail: IssueDetailView }) {
  const d = detail.latest_decision; const c = detail.issue.components;
  const latest = [...(detail.evidence.history?.items ?? [])].sort((a, b) => b.submitted_at.localeCompare(a.submitted_at))[0] ?? null;
  const cls = detail.facts.classification; const jur = detail.facts.jurisdiction;
  return (
    <div className="stack-6">
      {d ? (
        <div className="decision stack-2">
          <div className="row"><strong>{decisionLabel(d.decision_type)}</strong><span className="muted small">{d.actor_label}</span><Timestamp value={d.created_at} /></div>
          <p className="lead">{d.summary}</p>
          {d.evidence_ids.length > 0 && <div className="row">{d.evidence_ids.map((id) => <EvidenceImage key={id} evidenceId={id} role="Referenced" size="thumb" jobId={detail.current.job?.id ?? null} />)}</div>}
        </div>
      ) : <p className="muted">No decision recorded yet</p>}
      <div className="stack-2">
        <h3>Evidence points</h3>
        <KeyValue items={[
          { label: requirementLabel("image"), value: c.image }, { label: requirementLabel("independent_sources"), value: c.independent_sources },
          { label: requirementLabel("precise_geocode"), value: c.precise_geocode }, { label: requirementLabel("service_match"), value: c.service_match },
          { label: requirementLabel("persistence"), value: c.persistence }, { label: "Total", value: <Points value={detail.issue.evidence_score} threshold={70} /> },
        ]} />
      </div>
      {latest?.components && (
        <div className="stack-2">
          <h3>Verification points, latest proof</h3>
          <KeyValue items={[
            { label: requirementLabel("gps_within_30m"), value: latest.components.gps_within_30m }, { label: requirementLabel("after_later_than_before"), value: latest.components.after_later_than_before },
            { label: requirementLabel("target_removed"), value: latest.components.target_removed }, { label: requirementLabel("no_new_hazard"), value: latest.components.no_new_hazard },
            { label: requirementLabel("area_clear"), value: latest.components.area_clear },
            { label: "Total", value: <Points value={latest.total ?? 0} threshold={95} style="of" suffix="for payment" /> },
          ]} />
          {latest.prerequisites.length > 0 && <ul className="small">{latest.prerequisites.map((g) => <li key={g.name}>{requirementLabel(g.name)}: {g.allowed ? "passed" : `failed (${g.unmet.map(requirementLabel).join(", ")})`}</li>)}</ul>}
        </div>
      )}
      {(cls || jur) && (
        <div className="stack-2">
          <h3>Authority and scope</h3>
          <KeyValue items={[
            ...(cls ? [{ label: "Category", value: humanizeCode(cls.category) }, { label: "Primary target", value: cls.primary_target ?? "Unknown" }, { label: "Full cleanup scope", value: cls.full_cleanup_scope ?? "Unknown" }, { label: "Marked work area", value: cls.marked_work_area ?? "Unknown" }] : []),
            ...(jur ? [{ label: "Responsibility", value: jur.responsibility }] : []),
            ...((cls?.unknowns?.length ?? 0) > 0 ? [{ label: "Unknowns", value: cls!.unknowns.join(", ") }] : []),
          ]} />
        </div>
      )}
      {detail.current.allowed_next.length > 0 && <p className="small muted">Allowed next: {detail.current.allowed_next.map(requirementLabel).join(", ")}</p>}
    </div>
  );
}
