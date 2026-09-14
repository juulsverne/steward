import type { components } from "./api/schema";

type S = components["schemas"];

export type Outcome = "OK" | "DENIED" | "NEEDS_REVIEW" | "NOT_FOUND" | "ERROR";
export type InvocationStatus = "PENDING" | "RUNNING" | "WAITING" | "COMPLETED" | "ERROR";
export type IssueStatus =
  | "CANDIDATE" | "MONITORING" | "ACTIONABLE" | "RESOLUTION_ACTIVE" | "RESOLVED"
  | "DISPUTED" | "ROUTED_EXTERNAL" | "DUPLICATE" | "INVALID" | "ESCALATED";
export type JobStatus =
  | "POSTED" | "ASSIGNED" | "CHECKED_IN" | "PROOF_SUBMITTED" | "VERIFIED" | "PAID"
  | "REWORK_REQUIRED" | "REJECTED" | "CANCELLED";
export type DecisionType =
  | "MONITOR" | "MARK_ACTIONABLE" | "DISPUTE_OFFICIAL_STATUS" | "ROUTE_EXTERNAL"
  | "REQUEST_DISPATCH" | "REQUEST_SETTLEMENT" | "REQUEST_OPERATOR" | "REQUEST_REWORK" | "RESOLVE";
export type ActorType = "resident" | "crew" | "operator" | "service";
export type Provenance = "seeded" | "live" | "synthetic";
export type MarkerState = "watching" | "active" | "attention" | "resolved";

export interface ToolResult<T> {
  outcome: Outcome;
  reason_code: string | null;
  data: T | null;
  unmet: string[];
  allowed_next: string[];
  evidence_ids: string[];
  event_ids: number[];
}

export type DemoSessionView = S["DemoSessionView"];
export type PersonaChoice = S["PersonaChoice"];
export type ActorContext = S["ActorContext"];
export type BoardView = S["BoardView"];
export type BoardMarker = S["BoardMarker"];
export type BoardCounts = S["BoardCounts"];
export type BudgetAvailability = S["BudgetAvailability"];
export type IssueDetailView = S["IssueDetailView"];
export type IssueView = S["IssueView"];
export type IssueCurrentView = S["IssueCurrentView"];
export type IssueFactsView = S["IssueFactsView"];
export type IssueEvidenceView = S["IssueEvidenceView"];
export type SourceSummary = S["SourceSummary"];
export type ServiceLookupSummary = S["ServiceLookupSummary"];
export type PlanSummary = S["PlanSummary"];
export type JobSummary = S["JobSummary"];
export type PaymentSummary = S["PaymentSummary"];
export type DecisionSummary = S["DecisionSummary"];
export type ProofHistoryItem = S["ProofHistoryItem"];
export type IssueTimelineView = S["IssueTimelineView"];
export type TimelineEvent = S["TimelineEvent"];
export type ExceptionListPage = S["ExceptionListPage"];
export type ExceptionDetail = S["ExceptionDetail"];
export type CrewJobListView = S["CrewJobListView"];
export type CrewJobCard = S["CrewJobCard"];
export type CrewJobView = S["CrewJobView"];
export type ProofRequirements = S["ProofRequirements"];
export type EvidenceComponents = S["EvidenceComponents"];
export type VerificationComponents = S["VerificationComponents"];
export type GateRecord = S["GateRecord"];
export type IntakeReceiptView = S["IntakeReceiptView"];
export type ReceiptStatusView = S["ReceiptStatusView"];
export type ProofReceiptView = S["ProofReceiptView"];
export type RuntimeStatus = S["RuntimeStatus"];
export type EntityResult = S["EntityResult"];
export type PendingEntityResult = S["PendingEntityResult"];
export type ValidationView = S["ValidationView"];
