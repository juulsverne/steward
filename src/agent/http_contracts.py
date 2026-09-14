"""Dependency-light request DTOs shared by the API and later HTTP tools."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from . import contracts as c


class OperationalDecisionProposalRequest(c.Record):
    decision_type: c.OperationalDecisionType
    summary: c.Text = Field(max_length=2000)
    evidence_ids: tuple[c.OpaqueId, ...] = Field(default=(), max_length=64)
    basis: c.OperationalDecisionProposalBasis

    @model_validator(mode="after")
    def matching_basis(self):
        expected = {
            "dispatch": "REQUEST_DISPATCH",
            "settlement": "REQUEST_SETTLEMENT",
            "completion_operator": "REQUEST_OPERATOR",
            "authority": "REQUEST_OPERATOR",
            "no_vendor": "REQUEST_OPERATOR",
            "budget": "REQUEST_OPERATOR",
            "rework": "REQUEST_REWORK",
            "resolve": "RESOLVE",
        }[self.basis.kind]
        if self.decision_type != expected:
            raise ValueError("operational decision type does not match basis")
        return self


class PersonaRequest(c.Record):
    persona_id: c.OpaqueId


class PlanRequest(c.Record):
    classification_fact_id: c.OpaqueId


class DispatchRequest(c.Record):
    vendor_id: c.OpaqueId


class CheckinRequest(c.Record):
    latitude: float
    longitude: float
    accuracy_m: float | None = None
    claimed_at: c.Timestamp | None = None


class ProofMetadata(c.Record):
    before_observed_at: c.Timestamp | None = None
    after_observed_at: c.Timestamp | None = None


class InspectCompletionRequest(c.Record):
    submission_id: c.OpaqueId


class CompletionExceptionRequest(c.Record):
    submission_id: c.OpaqueId
    verification_id: c.OpaqueId
    denial_event_id: c.Positive
    reason_code: c.Text


class IssueExceptionRequest(c.Record):
    kind: Literal["authority", "no_vendor", "budget"]
    reason_code: c.Text
    denial_event_id: c.Positive | None = None


class RequestCompletionRequest(c.Record):
    submission_id: c.OpaqueId
    expected_job_revision: c.Nonnegative


class IssueCreateRequest(c.Record):
    signal_id: c.OpaqueId
    match_rationale: c.Text


class StoredSignalRequest(c.Record):
    signal_id: c.OpaqueId


class LinkSignalRequest(StoredSignalRequest):
    match_rationale: c.Text


class ClassificationProposalRequest(c.Record):
    signal_id: c.OpaqueId
    category: c.Text
    visible_objects: tuple[c.Text, ...] = ()
    hazards: tuple[c.Text, ...] = ()
    primary_target: c.Text | None = None
    full_cleanup_scope: c.Text | None = None
    marked_work_area: c.Text | None = None
    large_object_count: c.Nonnegative | None = None
    supporting_evidence_ids: tuple[c.OpaqueId, ...] = ()
    unknowns: tuple[c.Text, ...] = ()


class JurisdictionProposalRequest(c.Record):
    classification_fact_id: c.OpaqueId
    responsibility: Literal["district", "city", "private", "unknown"]
    supporting_fact_ids: tuple[c.OpaqueId, ...] = ()
    unknowns: tuple[c.Text, ...] = ()


class DecisionProposalRequest(c.Record):
    decision_type: c.DecisionType
    summary: c.Text
    evidence_ids: tuple[c.OpaqueId, ...] = ()


class InvestigationActionRequest(c.Record):
    decision_id: c.OpaqueId


class ExceptionListView(c.Record):
    exceptions: tuple[c.ExceptionDetail, ...]


class CandidateSignalView(c.Record):
    id: c.Text
    source_role: c.Text
    source_author_id: c.Text | None
    text: c.Text
    observed_at: c.Timestamp | None
    image_evidence_ids: tuple[c.Text, ...] = ()


class CandidateSignalsView(c.Record):
    candidates: tuple[CandidateSignalView, ...]
    truncated: bool = False


class SimilarIssueView(c.Record):
    id: c.Text
    status: c.IssueStatus
    location: c.Text
    evidence_score: c.Nonnegative


class SimilarIssuesView(c.Record):
    candidates: tuple[SimilarIssueView, ...]
    truncated: bool = False


class HealthView(c.Record):
    ok: bool


class IntakeReceiptView(c.Record):
    """Safe acknowledgment: receipt identity is the saved signal identity."""

    receipt_id: c.Text
    signal_id: c.Text
    received_at: c.Timestamp
    accepted: bool = True
    processing: str = "PENDING"


class ValidationDetail(c.Record):
    code: str = "INVALID_FIELD"
    location: str


class ValidationView(c.Record):
    errors: tuple[ValidationDetail, ...]


class PersonaChoice(c.Record):
    persona_id: c.OpaqueId
    label: c.Text
    actor_type: Literal["resident", "crew", "operator"]


class DemoSessionView(c.Record):
    sandbox: Literal[True] = True
    notice: str = "Demo sandbox — seeded personas; do not submit private information."
    actor: c.ActorContext | None = None
    personas: tuple[PersonaChoice, ...]


class ReceiptView(c.Record):
    receipt_id: c.Text
    signal_id: c.Text
    received_at: c.Timestamp
    accepted: Literal[True] = True
    processing: Literal["PENDING"] = "PENDING"


class IssueView(c.Record):
    id: c.Text
    category: c.Text
    location: c.Text
    status: c.IssueStatus
    state_revision: c.Nonnegative
    evidence_score: c.Nonnegative
    components: c.EvidenceComponents
    responsibility: c.Text | None
    hazards: tuple[c.Text, ...]


class CrewJobView(c.Record):
    id: c.Text
    issue_id: c.Text
    vendor_id: c.Text
    status: c.JobStatus
    state_revision: c.Nonnegative
    location: c.Text
    scope: c.Text
    work_area: c.Text
    price_cents: c.Positive
    proof_requirements: c.ProofRequirements
    accepted_at: c.Timestamp | None
    checkin_claimed_at: c.Timestamp | None = None
    checked_in_at: c.Timestamp | None
    submitted_at: c.Timestamp | None
    latest_submission_id: c.Text | None
    rework_instructions: c.Text | None
    simulated: Literal[True] = True
    plan_id: c.Text
    primary_target: c.Text | None = None
    dispatch_location: c.LocationRecord | None = None
    required_equipment: tuple[c.Text, ...] = ()
    crew_count: c.Positive
    reservation_id: c.Text | None = None
    policy_version: c.Text


class EvidenceView(c.Record):
    id: c.Text
    content_type: Literal["image/jpeg", "image/png"]
    provenance: c.Provenance
    observed_at: c.Timestamp | None
    received_at: c.Timestamp


class PageInfo(c.Record):
    next_cursor: c.Text | None = None
    truncated: bool = False


class SourceSummary(c.Record):
    id: c.Text
    source_role: c.Text
    provenance: c.Provenance
    observed_at: c.Timestamp | None
    received_at: c.Timestamp
    reported_location: c.Text
    evidence_ids: tuple[c.Text, ...] = ()


class SourcePage(PageInfo):
    items: tuple[SourceSummary, ...]


class ServiceLookupSummary(c.Record):
    id: c.Text
    signal_id: c.Text
    outcome: c.Text
    status: c.Text | None = None
    completed_at: c.Timestamp | None = None
    looked_up_at: c.Timestamp
    source_mode: c.Text
    provenance: c.Provenance
    error_code: c.Text | None = None


class ServiceLookupPage(PageInfo):
    items: tuple[ServiceLookupSummary, ...]


class PlanSummary(c.Record):
    id: c.Text
    primary_target: c.Text | None = None
    scope: c.Text
    work_area: c.Text
    required_equipment: tuple[c.Text, ...]
    quote_cents: c.Positive
    policy_version: c.Text
    dispatch_location: c.LocationRecord | None = None


class JobSummary(c.Record):
    id: c.Text
    vendor_id: c.Text
    vendor_label: c.Text
    status: c.JobStatus
    state_revision: c.Nonnegative
    quote_cents: c.Positive
    latest_submission_id: c.Text | None = None
    reservation_id: c.Text | None = None
    payment_id: c.Text | None = None
    simulated: Literal[True] = True


class PaymentSummary(c.Record):
    id: c.Text
    job_id: c.Text
    submission_id: c.Text
    verification_id: c.Text
    amount_cents: c.Positive
    simulated: Literal[True] = True


class DecisionSummary(c.Record):
    id: c.Text
    decision_type: c.DecisionType
    summary: c.Text
    actor_label: c.Text
    actor_type: c.ActorType
    next_actor: c.ActorType | None = None
    next_event: c.Text | None = None
    created_at: c.Timestamp
    evidence_ids: tuple[c.Text, ...] = ()
    event_id: c.Positive


class IssueCurrentView(c.Record):
    next_actor: c.ActorType | None = None
    allowed_next: tuple[c.Text, ...] = ()
    plan: PlanSummary | None = None
    job: JobSummary | None = None
    exception: c.ExceptionDetail | None = None
    payment: PaymentSummary | None = None


class IssueFactsView(c.Record):
    classification: c.ClassificationFact | None = None
    jurisdiction: c.JurisdictionFact | None = None
    geocode: c.GeocodeFact | None = None
    official_conflict_record_id: c.Text | None = None
    official_record_status: c.Text | None = None
    official_conflict_state: c.Text | None = None
    official_completed_at: c.Timestamp | None = None


class ProofHistoryItem(c.Record):
    submission_id: c.Text
    job_id: c.Text
    verification_id: c.Text | None = None
    before_evidence_id: c.Text | None = None
    after_evidence_id: c.Text | None = None
    submitted_at: c.Timestamp
    findings: c.VisionFindings | None = None
    components: c.VerificationComponents | None = None
    total: c.Nonnegative | None = None
    prerequisites: tuple[c.GateRecord, ...] = ()
    unmet: tuple[c.Text, ...] = ()
    accepted: bool = False


class ProofHistoryPage(PageInfo):
    items: tuple[ProofHistoryItem, ...]


class IssueEvidenceView(c.Record):
    original_before_evidence_id: c.Text | None = None
    current_after_evidence_id: c.Text | None = None
    latest_submission_id: c.Text | None = None
    verification_id: c.Text | None = None
    inspection_id: c.Text | None = None
    history: ProofHistoryPage | None = None
    accepted_submission_id: c.Text | None = None
    accepted_verification_id: c.Text | None = None
    resolved_at: c.Timestamp | None = None


class IssueDetailView(c.Record):
    issue: IssueView
    current: IssueCurrentView
    sources: SourcePage
    service_records: ServiceLookupPage
    facts: IssueFactsView
    evidence: IssueEvidenceView
    latest_decision: DecisionSummary | None = None
    timeline_url: c.Text


class TimelineEntityIds(c.Record):
    signal_id: c.Text | None = None
    job_id: c.Text | None = None
    submission_id: c.Text | None = None
    exception_id: c.Text | None = None
    decision_id: c.Text | None = None
    payment_id: c.Text | None = None


class TimelineEvent(c.Record):
    id: c.Positive
    occurred_at: c.Timestamp
    type: c.Text
    actor_label: c.Text
    actor_type: c.ActorType
    outcome: c.Outcome | None = None
    reason_code: c.Text | None = None
    summary: c.Text | None = None
    entity_ids: TimelineEntityIds
    evidence_ids: tuple[c.Text, ...] = ()
    provenance: c.Provenance | None = None
    simulated: bool | None = None
    # A deliberately narrow historical projection.  It is populated only from the
    # immutable score written by Store._link_signal, never from arbitrary event JSON.
    evidence_score: c.Nonnegative | None = None
    evidence_components: c.EvidenceComponents | None = None


class IssueTimelineView(PageInfo):
    issue_id: c.Text
    events: tuple[TimelineEvent, ...]


class BoardCounts(c.Record):
    watching: c.Nonnegative
    active: c.Nonnegative
    resolved: c.Nonnegative
    attention: c.Nonnegative


class BoardMarker(c.Record):
    issue_id: c.Text
    status: c.IssueStatus
    marker_state: Literal["watching", "active", "attention", "resolved"]
    latitude: float | None = None
    longitude: float | None = None
    accuracy_m: float | None = None
    location_provenance: c.Provenance | None = None
    location_unknown_reason: c.Text | None = None
    label: c.Text
    current_job_id: c.Text | None = None
    payment_id: c.Text | None = None
    simulated: bool | None = None


class BoardView(PageInfo):
    as_of: c.Timestamp
    district_id: c.Text
    policy_version: c.Text
    counts: BoardCounts
    budget: c.BudgetAvailability
    markers: tuple[BoardMarker, ...]


class ExceptionListPage(PageInfo):
    exceptions: tuple[c.ExceptionDetail, ...]
    pending_count: c.Nonnegative
    decided_count: c.Nonnegative


class CrewJobCard(c.Record):
    id: c.Text
    issue_id: c.Text
    status: c.JobStatus
    state_revision: c.Nonnegative
    location: c.Text
    scope: c.Text
    price_cents: c.Positive
    simulated: Literal[True] = True
    latest_submission_id: c.Text | None = None
    pending_exception_status: c.Text | None = None
    created_at: c.Timestamp


class CrewJobListView(PageInfo):
    jobs: tuple[CrewJobCard, ...]


class EvidenceDetailView(EvidenceView):
    role: Literal["intake", "before", "after"]
    issue_id: c.Text | None = None
    job_id: c.Text | None = None
    submission_id: c.Text | None = None
    inspection_status: c.Text | None = None


class ReceiptStatusView(ReceiptView):
    processing: c.InvocationStatus = "PENDING"
    invocation_id: c.Text | None = None
    updated_at: c.Timestamp | None = None
    reason_code: c.Text | None = None


class ProofReceiptView(c.Record):
    submission_id: c.Text
    job_id: c.Text
    invocation_id: c.Text
    processing: c.InvocationStatus
    updated_at: c.Timestamp | None = None
    reason_code: c.Text | None = None


class VendorOptions(c.Record):
    plan: c.PlanRecord
    issue_revision: c.Nonnegative
    vendors: tuple[c.VendorRecord, ...]
