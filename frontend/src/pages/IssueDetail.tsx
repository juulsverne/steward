import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router";
import "./IssueDetail.css";
import { ApiError, read } from "../api/client";
import { actorTypeLabel, exceptionKind, exceptionStatus, humanizeCode, issueStatus, jobStatus, requirementLabel } from "../api/labels";
import { actorType, useSession } from "../api/session";
import { DecisionCard } from "../components/DecisionCard";
import { DecisionTimeline } from "../components/DecisionTimeline";
import { EvidenceComparison } from "../components/EvidenceComparison";
import { KeyValue } from "../components/KeyValue";
import { Money } from "../components/Money";
import { PageHeader } from "../components/PageHeader";
import { Points } from "../components/Points";
import { RequirePersona } from "../components/RequirePersona";
import { SectionCard } from "../components/SectionCard";
import { ErrorNotice, PendingState } from "../components/States";
import { StatusBadge } from "../components/StatusBadge";
import { Timestamp } from "../components/Timestamp";
import type { IssueDetailView, IssueTimelineView } from "../types";

function nextText(d: IssueDetailView): string {
  if (d.issue.status === "RESOLVED") return "Closed with accepted proof.";
  if (d.current.exception?.status === "PENDING") return "Next actor: Operator, decision waiting.";
  if (d.current.next_actor) return `Next actor: ${actorTypeLabel(d.current.next_actor)}${d.latest_decision?.next_event ? `, waiting for ${requirementLabel(d.latest_decision.next_event)}` : ""}.`;
  if (d.issue.status === "MONITORING" || d.issue.status === "CANDIDATE") return `Waiting for: ${d.latest_decision?.next_event ? requirementLabel(d.latest_decision.next_event) : "a new observation or an official status change"}.`;
  return d.current.allowed_next.length ? `Allowed next: ${d.current.allowed_next.map(requirementLabel).join(", ")}.` : "No action pending.";
}

export function IssueDetail() { return <RequirePersona allow={["operator"]}><IssueContent /></RequirePersona>; }

function IssueContent() {
  const { issueId = "" } = useParams();
  const session = useSession(); const who = actorType(session);
  const [detail, setDetail] = useState<{ status: "pending" | "ready" | "error"; data: IssueDetailView | null; error: unknown }>({ status: "pending", data: null, error: null });
  const [events, setEvents] = useState<{ status: "pending" | "ready" | "error"; data: IssueTimelineView | null; error: unknown }>({ status: "pending", data: null, error: null });
  const load = useCallback(async () => {
    try { setDetail({ status: "ready", data: await read<IssueDetailView>(`/api/issues/${encodeURIComponent(issueId)}`), error: null }); }
    catch (error) { setDetail((s) => ({ status: "error", data: s.data, error: error instanceof ApiError ? error : new Error(String(error)) })); }
    try { setEvents({ status: "ready", data: await read<IssueTimelineView>(`/api/issues/${encodeURIComponent(issueId)}/events?limit=50`), error: null }); }
    catch (error) { setEvents((s) => ({ status: "error", data: s.data, error: error instanceof ApiError ? error : new Error(String(error)) })); }
  }, [issueId]);
  useEffect(() => { void load(); }, [load]);

  if (detail.status === "pending") return <div className="page"><PageHeader title="Issue" /><PendingState /></div>;
  const d = detail.data;
  if (!d) return <div className="page"><PageHeader title="Issue" /><ErrorNotice error={detail.error} onRetry={() => void load()} /></div>;
  const status = issueStatus(d.issue.status); const job = d.current.job; const plan = d.current.plan; const ex = d.current.exception; const pay = d.current.payment;
  return (
    <div className="page issue">
      <PageHeader eyebrow={humanizeCode(d.issue.category)} title={d.issue.location}
        meta={<>
          <StatusBadge label={status.label} tone={status.tone} />
          <Points value={d.issue.evidence_score} threshold={70} />
          {d.issue.responsibility && <span>Responsibility: {d.issue.responsibility}</span>}
          {d.issue.hazards.length > 0 && <span>Hazards: {d.issue.hazards.join(", ")}</span>}
        </>}
        actions={<>
          {who === "operator" && ex?.status === "PENDING" && <Link className="btn btn--primary" to={`/inbox?exception=${ex.id}`}>Open in Inbox</Link>}
        </>} />
      {detail.status === "error" && <ErrorNotice error={detail.error} title="Refresh failed, showing the last loaded data" onRetry={() => void load()} />}
      <p className="issue__next lead">{nextText(d)}</p>
      {d.latest_decision && <p className="issue__last small muted">Last decision recorded <Timestamp value={d.latest_decision.created_at} /> by {d.latest_decision.actor_label}</p>}
      <div className="issue__grid">
        <div className="issue__main stack-6">
          <SectionCard id="evidence" title="Evidence"><EvidenceComparison detail={d} /></SectionCard>
          <SectionCard id="decision" title="Decision and policy"><DecisionCard detail={d} /></SectionCard>
          <SectionCard id="timeline" title="Timeline">
            {events.status === "pending" ? <PendingState /> : events.data ? <DecisionTimeline events={events.data.events} /> : <ErrorNotice error={events.error} onRetry={() => void load()} />}
            {events.data && events.data.truncated && <p className="small muted">Showing the 50 most recent events.</p>}
          </SectionCard>
        </div>
        <aside className="issue__aside stack-6">
          <SectionCard id="plan" title="Plan and job">
            {plan ? (
              <div className="stack-4">
                <KeyValue items={[{ label: "Scope", value: plan.scope }, { label: "Primary target", value: plan.primary_target ?? "Unknown" }, { label: "Work area", value: plan.work_area },
                  { label: "Equipment", value: plan.required_equipment.join(", ") || "None" }, { label: "Quote", value: <Money cents={plan.quote_cents} /> }, { label: "Policy", value: plan.policy_version }]} />
                {job && <>
                  <h3>Job {job.id}</h3>
                  <KeyValue items={[{ label: "Vendor", value: job.vendor_label }, { label: "Status", value: <StatusBadge label={jobStatus(job.status).label} tone={jobStatus(job.status).tone} /> },
                    { label: "Quote", value: <Money cents={job.quote_cents} simulated /> }, { label: "Reservation", value: job.reservation_id ?? "None" }, { label: "Dispatch", value: <StatusBadge label="Simulated dispatch" tone="neutral" /> }]} />
                  {job.status === "REWORK_REQUIRED" && <p className="small muted">Rework keeps the same plan, quote and reservation.</p>}
                </>}
                {pay && <><h3>Settlement</h3><KeyValue items={[{ label: "Amount", value: <Money cents={pay.amount_cents} simulated /> }, { label: "Submission", value: pay.submission_id }, { label: "Verification", value: pay.verification_id }]} /></>}
                {ex && <><h3>Operator exception</h3><KeyValue items={[{ label: "Kind", value: exceptionKind(ex.kind) }, { label: "Status", value: <StatusBadge label={exceptionStatus(ex.status).label} tone={exceptionStatus(ex.status).tone} /> }, { label: "Reason", value: requirementLabel(ex.reason_code) }]} />
                  {who === "operator" && <Link to={`/inbox?exception=${ex.id}`}>Open in Inbox</Link>}</>}
              </div>
            ) : <p className="muted">No plan yet. Steward plans only when the issue is actionable and within district authority.</p>}
          </SectionCard>
          <SectionCard id="facts" title="Record">
            <KeyValue items={[{ label: "Issue", value: <code>{d.issue.id}</code> }, { label: "Revision", value: d.issue.state_revision }, { label: "Resolved", value: <Timestamp value={d.evidence.resolved_at} /> }]} />
          </SectionCard>
        </aside>
      </div>
    </div>
  );
}
