import type { ActorType, DecisionType, InvocationStatus, IssueStatus, JobStatus, MarkerState, Outcome, Provenance } from "../types";

export type Tone = "watching" | "active" | "attention" | "resolved" | "denied" | "neutral";
type Entry = { label: string; tone: Tone };

const ISSUE: Record<IssueStatus, Entry> = {
  CANDIDATE: { label: "Candidate", tone: "watching" }, MONITORING: { label: "Monitoring", tone: "watching" },
  ACTIONABLE: { label: "Actionable", tone: "active" }, RESOLUTION_ACTIVE: { label: "Resolution active", tone: "active" },
  RESOLVED: { label: "Resolved", tone: "resolved" }, DISPUTED: { label: "Official status disputed", tone: "active" },
  ROUTED_EXTERNAL: { label: "Routed externally", tone: "neutral" }, DUPLICATE: { label: "Duplicate", tone: "neutral" },
  INVALID: { label: "Invalid", tone: "denied" }, ESCALATED: { label: "Escalated to operator", tone: "attention" },
};
const JOB: Record<JobStatus, Entry> = {
  POSTED: { label: "Posted", tone: "watching" }, ASSIGNED: { label: "Assigned", tone: "active" },
  CHECKED_IN: { label: "Checked in", tone: "active" }, PROOF_SUBMITTED: { label: "Proof submitted", tone: "active" },
  VERIFIED: { label: "Verified", tone: "resolved" }, PAID: { label: "Paid, simulated", tone: "resolved" },
  REWORK_REQUIRED: { label: "Rework required", tone: "attention" }, REJECTED: { label: "Rejected", tone: "denied" },
  CANCELLED: { label: "Cancelled", tone: "neutral" },
};
const DECISION: Record<DecisionType, string> = {
  MONITOR: "Monitor and wait", MARK_ACTIONABLE: "Mark actionable", DISPUTE_OFFICIAL_STATUS: "Dispute official status",
  ROUTE_EXTERNAL: "Route externally", REQUEST_DISPATCH: "Request dispatch", REQUEST_SETTLEMENT: "Request settlement",
  REQUEST_OPERATOR: "Request operator decision", REQUEST_REWORK: "Request rework", RESOLVE: "Resolve",
};
const INVOCATION: Record<InvocationStatus, { gloss: string; tone: Tone }> = {
  PENDING: { gloss: "queued", tone: "watching" }, RUNNING: { gloss: "Steward is processing", tone: "active" },
  WAITING: { gloss: "waiting for a crew or operator event", tone: "watching" },
  COMPLETED: { gloss: "finished", tone: "resolved" }, ERROR: { gloss: "stopped with an error", tone: "denied" },
};
const REQUIREMENTS: Record<string, string> = {
  check_in: "Check in on site", before_image: "Before photo", fresh_after_image: "Fresh after photo", same_scene: "Same scene",
  target_removed: "Target removed", no_new_hazard: "No new hazard", area_clear: "Area clear",
  gps_within_30m: "GPS check-in within 30 m", after_later_than_before: "After photo later than before photo",
  image: "Image", independent_sources: "Independent sources", precise_geocode: "Precise geocode", service_match: "Service match", persistence: "Persistence",
};

export function issueStatus(s: IssueStatus): Entry { return ISSUE[s] ?? { label: humanizeCode(s), tone: "neutral" }; }
export function jobStatus(s: JobStatus): Entry { return JOB[s] ?? { label: humanizeCode(s), tone: "neutral" }; }
export function markerTone(m: MarkerState): Tone { return m; }
export function decisionLabel(d: DecisionType): string { return DECISION[d] ?? humanizeCode(d); }
export function isRequestDecision(d: DecisionType): boolean { return d.startsWith("REQUEST_"); }
export function outcomeLabel(o: Outcome, opts: { requested?: boolean } = {}): Entry {
  if (o === "OK") return opts.requested ? { label: "Requested", tone: "active" } : { label: "Saved", tone: "resolved" };
  if (o === "DENIED") return { label: "Denied", tone: "denied" };
  if (o === "NEEDS_REVIEW") return { label: "Needs review", tone: "attention" };
  if (o === "NOT_FOUND") return { label: "Not found", tone: "denied" };
  return { label: "Error", tone: "denied" };
}
export function invocationGloss(s: InvocationStatus): Entry & { gloss: string } {
  const e = INVOCATION[s] ?? { gloss: humanizeCode(s), tone: "neutral" as Tone };
  return { label: s, tone: e.tone, gloss: e.gloss };
}
export function invocationIsTerminal(s: InvocationStatus | null | undefined): boolean { return s === "COMPLETED" || s === "WAITING" || s === "ERROR"; }
export function actorTypeLabel(a: ActorType): string { return { resident: "Resident", crew: "Crew", operator: "Operator", service: "Steward" }[a] ?? a; }
export function exceptionKind(k: "completion" | "authority" | "no_vendor" | "budget"): string {
  return { completion: "Completion blocked", authority: "Authority escalation", no_vendor: "No eligible provider", budget: "Budget escalation" }[k];
}
export function exceptionStatus(s: "PENDING" | "DECIDED" | "HANDLED" | "CANCELLED"): Entry {
  return { PENDING: { label: "Decision waiting", tone: "attention" }, DECIDED: { label: "Decided", tone: "active" },
    HANDLED: { label: "Handled", tone: "neutral" }, CANCELLED: { label: "Cancelled", tone: "neutral" } }[s] as Entry;
}
export function humanizeCode(code: string): string {
  const words = code.toLowerCase().replace(/[_-]+/g, " ").trim();
  return words.charAt(0).toUpperCase() + words.slice(1);
}
export function provenanceTitle(p: Provenance): string {
  return { live: "Live: captured during this run", seeded: "Seeded: fixture metadata supplied for the demo", synthetic: "Synthetic: generated demo image with recorded provenance" }[p];
}
export function requirementLabel(key: string): string { return REQUIREMENTS[key] ?? humanizeCode(key); }
