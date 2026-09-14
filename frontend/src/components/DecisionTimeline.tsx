import { useState } from "react";
import { actorTypeLabel, humanizeCode, outcomeLabel } from "../api/labels";
import type { TimelineEvent } from "../types";
import { EvidenceImage } from "./EvidenceImage";
import { Points } from "./Points";
import { StatusBadge } from "./StatusBadge";
import { Timestamp } from "./Timestamp";

const DECISION_TYPES = /DECISION|DENIED|SETTLE|PAYMENT|DISPATCH|DISPUTE|RESOLVED|REWORK|VERIF|ESCALAT/;

export function DecisionTimeline({ events }: { events: TimelineEvent[] }) {
  const [onlyDecisions, setOnlyDecisions] = useState(false);
  const shown = onlyDecisions ? events.filter((e) => DECISION_TYPES.test(e.type)) : events;
  return (
    <div className="stack-3">
      <label className="row small"><input type="checkbox" checked={onlyDecisions} onChange={(e) => setOnlyDecisions(e.target.checked)} /> Show only decisions and outcomes</label>
      <ol className="timeline">
        {shown.map((e) => {
          const requested = e.type.startsWith("REQUEST") || e.type.includes("REQUESTED");
          const o = e.outcome ? outcomeLabel(e.outcome, { requested }) : null;
          return (
            <li key={e.id} className="timeline__item">
              <div className="timeline__when"><Timestamp value={e.occurred_at} /></div>
              <div className="timeline__body stack-2">
                <div className="row">
                  <strong>{humanizeCode(e.type)}</strong><code className="small muted">{e.type}</code>
                  {o && <StatusBadge label={o.label} tone={e.outcome === "DENIED" ? "denied" : o.tone} />}
                  {e.simulated && <StatusBadge label="Simulated" tone="neutral" />}
                </div>
                <p className="small muted">{e.actor_label} ({actorTypeLabel(e.actor_type)}){e.reason_code ? `, ${humanizeCode(e.reason_code)}` : ""}</p>
                {e.summary && <p>{e.summary}</p>}
                {e.evidence_score !== null && e.evidence_score !== undefined && <Points value={e.evidence_score} threshold={70} />}
                {e.evidence_ids.length > 0 && <div className="row">{e.evidence_ids.map((id) => <EvidenceImage key={id} evidenceId={id} role="Evidence" size="thumb" jobId={e.entity_ids.job_id} />)}</div>}
              </div>
            </li>
          );
        })}
      </ol>
    </div>
  );
}
